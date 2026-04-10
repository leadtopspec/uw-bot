import csv
import os
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
print("TOKEN:", TOKEN)

PRODUCTS = {
    "American Amicable": {"Senior Choice": {"coverage_type": "Whole Life", "min_age": 50, "max_age": 85, "csv_file": "Carrier Condition Sheet - AMAM SC.csv"}, "Family Choice": {"coverage_type": "Whole Life", "min_age": 0, "max_age": 49, "csv_file": "Carrier Condition Sheet - AMAM FC.csv"}},
    "Mutual of Omaha": {"Living Promise": {"coverage_type": "Whole Life", "min_age": 45, "max_age": 85, "csv_file": "Carrier Condition Sheet - MOO LP.csv"}},
    "AIG": {"SIWL": {"coverage_type": "Whole Life", "min_age": 0, "max_age": 85, "csv_file": "Carrier Condition Sheet - AIG SIWL.csv"}, "GIWL": {"coverage_type": "Guaranteed Issue Whole Life", "min_age": 50, "max_age": 80, "special_case": "fallback"}},
    "Americo": {"Eagle Select": {"coverage_type": "Whole Life", "min_age": 40, "max_age": 85, "csv_file": "Carrier Condition Sheet - AMERICO.csv"}}
}

RESULT_PRIORITY = {"Immediate": 1, "Level": 1, "Allowed": 1, "Eagle Select 1": 1, "Graded": 2, "Eagle Select 2": 2, "Eagle Select 2 Non-nicotine": 2, "Eagle Select 2 Nicotine": 2, "ROP": 3, "Return of Premium": 3, "Eagle Select 3": 3, "Guaranteed Issue Fallback": 4, "Decline": 99, "DECLINE": 99, "No Coverage": 99, "No Match Found": 100}
BAD_OUTCOMES = {"Decline", "DECLINE", "No Coverage", "No Match Found"}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CACHED_CONDITIONS = None

def load_rules(file_path):
    rules = []
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cond = row.get("CONDITION", "").strip()
            crit = row.get("CRITERIA", "").strip()
            decision = (row.get("PLAN TO APPLY FOR", "") or row.get("DECISION", "")).strip()
            if cond and decision:
                rules.append({"condition": cond, "criteria": crit, "decision": decision})
    return rules

def load_all_conditions():
    global CACHED_CONDITIONS
    if CACHED_CONDITIONS is not None:
        return CACHED_CONDITIONS
    all_conds = set()
    for carrier, products in PRODUCTS.items():
        for pname, info in products.items():
            cf = info.get("csv_file")
            if cf and os.path.exists(cf):
                try:
                    all_conds.update(r["condition"] for r in load_rules(cf))
                except:
                    pass
    CACHED_CONDITIONS = sorted(list(all_conds))
    return CACHED_CONDITIONS

def match_rule(user_text, rule):
    text, cond, crit = user_text.lower().strip(), rule["condition"].lower().strip(), rule["criteria"].lower().strip()
    score = 100 if text == cond else (40 if cond and cond in text else (100 if (text == "copd" and cond == "copd") or (text == "diabetes" and cond == "diabetes") else (5 if cond.startswith(text + " ") else 0)))
    text_words, cond_words, crit_words = set(w.strip() for w in text.replace("/", " ").replace(",", " ").split() if w.strip()), set(w.strip() for w in cond.replace("/", " ").replace(",", " ").split() if w.strip()), set(w.strip() for w in crit.replace("/", " ").replace(",", " ").split() if w.strip())
    score += len(text_words & cond_words) * 8 + len(text_words & crit_words) * 6
    return score - 8 if crit and len(text_words & crit_words) == 0 else score

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

async def process_uw_query(age, conditions):
    user_text = conditions.lower().strip()
    chart_results, fallback_results, file_errors = [], [], []
    
    if 50 <= age <= 85 and ("copd" in user_text or "diabetes" in user_text) and "oxygen" not in user_text:
        chart_results.append({"carrier": "American Amicable", "product": "Senior Choice", "coverage_type": "Whole Life", "decision": "Immediate", "score": 999999, "forced": True, "matched_condition": "AMAM playbook override", "criteria": "COPD/diabetes often gets AMAM Immediate first"})
    
    for carrier, products in PRODUCTS.items():
        for product_name, info in products.items():
            if not (info["min_age"] <= age <= info["max_age"]):
                continue
            if info.get("special_case") == "fallback":
                fallback_results.append({"carrier": carrier, "product": product_name, "coverage_type": info["coverage_type"], "decision": "Guaranteed Issue Fallback", "score": 1, "forced": False, "matched_condition": "", "criteria": "Use only as last resort"})
                continue
            if carrier == "American Amicable" and product_name == "Senior Choice" and 50 <= age <= 85 and ("copd" in user_text or "diabetes" in user_text) and "oxygen" not in user_text:
                continue
            csv_file = info.get("csv_file")
            if not csv_file or not os.path.exists(csv_file):
                file_errors.append(f"{carrier} — {product_name}")
                continue
            try:
                rules = load_rules(csv_file)
                matched_rules = [{"condition": r["condition"], "criteria": r["criteria"], "decision": r["decision"], "score": match_rule(user_text, r)} for r in rules if match_rule(user_text, r) > 0]
                if matched_rules:
                    matched_rules.sort(key=lambda r: (-r["score"], RESULT_PRIORITY.get(r["decision"], 50)))
                    best = matched_rules[0]
                    chart_results.append({"carrier": carrier, "product": product_name, "coverage_type": info["coverage_type"], "decision": best["decision"], "score": best["score"], "forced": False, "matched_condition": best["condition"], "criteria": best["criteria"] or "No extra criteria listed."})
                else:
                    chart_results.append({"carrier": carrier, "product": product_name, "coverage_type": info["coverage_type"], "decision": "No Match Found", "score": 0, "forced": False, "matched_condition": "", "criteria": "No chart row matched this input yet."})
            except Exception as e:
                file_errors.append(f"{carrier} — {product_name} ({str(e)})")
    
    if not chart_results and file_errors:
        return None, f"❌ **Chart files not loading**\n\n**Age:** {age}\n**Input:** {conditions}"
    
    chart_results.sort(key=lambda x: (0 if x.get("forced") else 1, RESULT_PRIORITY.get(x["decision"], 50), -x["score"]))
    has_real_option = any(r["decision"] not in BAD_OUTCOMES for r in chart_results)
    final_results = chart_results + (fallback_results if not has_real_option else [])
    final_results.sort(key=lambda x: (0 if x.get("forced") else 1, RESULT_PRIORITY.get(x["decision"], 50), -x["score"]))
    
    if not final_results:
        return None, f"❌ **No Coverage Available**\n\n**Age:** {age}\n**Input:** {conditions}"
    
    best = final_results[0]
    embed = discord.Embed(title="🩺 UW RESULT", color=discord.Color.blue())
    embed.add_field(name="Age", value=str(age), inline=True)
    embed.add_field(name="Input", value=conditions, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="🏆 Best Fit", value=f"• **Carrier:** {best['carrier']}\n• **Product:** {best['product']}\n• **Coverage:** {best['coverage_type']}\n• **Result:** **{best['decision']}**", inline=False)
    embed.add_field(name="📋 Criteria", value=best['criteria'], inline=False)
    embed.add_field(name="📊 All Options", value="\n".join([f"• **{r['carrier']} — {r['product']}** → **{r['decision']}**" for r in final_results]), inline=False)
    return embed, None

@bot.tree.command(name="uw", description="Check underwriting eligibility")
@app_commands.describe(age="Client age", conditions="Health conditions")
async def slash_uw(interaction, age: int, conditions: str):
    await interaction.response.defer()
    embed, error = await process_uw_query(age, conditions)
    await interaction.followup.send(embed=embed if embed else None, content=error if error else None)

@bot.tree.command(name="carriers", description="List carriers")
async def slash_carriers(interaction):
    embed = discord.Embed(title="📋 Available Carriers", color=discord.Color.green())
    for carrier, products in PRODUCTS.items():
        embed.add_field(name=carrier, value=", ".join(products.keys()), inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="conditions", description="List all conditions")
async def slash_conditions(interaction):
    await interaction.response.defer()
    conds = load_all_conditions()
    embed = discord.Embed(title=f"🏥 Conditions ({len(conds)} total)", color=discord.Color.purple())
    embed.description = "\n".join(conds[:50])
    if len(conds) > 50:
        embed.description += f"\n\n... and {len(conds) - 50} more conditions"
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="help", description="Show help")
async def slash_help(interaction):
    embed = discord.Embed(title="📖 UW Bot Help", color=discord.Color.gold())
    embed.add_field(name="/uw <age> <conditions>", value="Check eligibility", inline=False)
    embed.add_field(name="/carriers", value="List carriers", inline=False)
    embed.add_field(name="/conditions", value="List conditions", inline=False)
    embed.add_field(name="/help", value="Show this message", inline=False)
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
