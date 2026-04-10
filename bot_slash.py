import csv
import os
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")

PRODUCTS = {
    "American Amicable": {"Senior Choice": {"coverage_type": "Whole Life", "min_age": 50, "max_age": 85, "csv_file": "Carrier Condition Sheet - AMAM SC.csv"}, "Family Choice": {"coverage_type": "Whole Life", "min_age": 0, "max_age": 49, "csv_file": "Carrier Condition Sheet - AMAM FC.csv"}},
    "Mutual of Omaha": {"Living Promise": {"coverage_type": "Whole Life", "min_age": 45, "max_age": 85, "csv_file": "Carrier Condition Sheet - MOO LP.csv"}},
    "AIG": {"SIWL": {"coverage_type": "Whole Life", "min_age": 0, "max_age": 85, "csv_file": "Carrier Condition Sheet - AIG SIWL.csv"}, "GIWL": {"coverage_type": "Guaranteed Issue Whole Life", "min_age": 50, "max_age": 80, "special_case": "fallback"}},
    "Americo": {"Eagle Select": {"coverage_type": "Whole Life", "min_age": 40, "max_age": 85, "csv_file": "Carrier Condition Sheet - AMERICO.csv"}}
}

RESULT_PRIORITY = {"Immediate": 1, "Level": 1, "Allowed": 1, "Eagle Select 1": 1, "Graded": 2, "Eagle Select 2": 2, "Eagle Select 2 Non-nicotine": 2, "Eagle Select 2 Nicotine": 2, "ROP": 3, "Return of Premium": 3, "Eagle Select 3": 3, "Guaranteed Issue Fallback": 4, "Decline": 99, "DECLINE": 99, "No Coverage": 99, "No Match Found": 100}
BAD_OUTCOMES = {"Decline", "DECLINE", "No Coverage", "No Match Found"}
DECISION_COLORS = {"Immediate": 0x00ff41, "Level": 0x00ff41, "Allowed": 0x00ff41, "Eagle Select 1": 0x00ff41, "Graded": 0xffaa00, "Eagle Select 2": 0xffaa00, "Eagle Select 2 Non-nicotine": 0xffaa00, "Eagle Select 2 Nicotine": 0xffaa00, "ROP": 0xff6b6b, "Return of Premium": 0xff6b6b, "Eagle Select 3": 0xff6b6b, "Guaranteed Issue Fallback": 0x9370db, "Decline": 0xff0000, "DECLINE": 0xff0000, "No Coverage": 0xff0000, "No Match Found": 0x808080}
DECISION_EMOJI = {"Immediate": "✅", "Level": "✅", "Allowed": "✅", "Eagle Select 1": "✅", "Graded": "⚠️", "Eagle Select 2": "⚠️", "Eagle Select 2 Non-nicotine": "⚠️", "Eagle Select 2 Nicotine": "⚠️", "ROP": "📋", "Return of Premium": "📋", "Eagle Select 3": "📋", "Guaranteed Issue Fallback": "🛡️", "Decline": "❌", "DECLINE": "❌", "No Coverage": "❌", "No Match Found": "❓"}

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
    chart_results = []
    fallback_results = []
    file_errors = []
    
    amam_sc_result = None
    
    for carrier, products in PRODUCTS.items():
        for product_name, info in products.items():
            if not (info["min_age"] <= age <= info["max_age"]):
                continue
            
            if info.get("special_case") == "fallback":
                fallback_results.append({"carrier": carrier, "product": product_name, "coverage_type": info["coverage_type"], "decision": "Guaranteed Issue Fallback", "score": 0, "forced": False, "matched_condition": "", "criteria": "Use as last resort if no standard product available"})
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
                    result = {"carrier": carrier, "product": product_name, "coverage_type": info["coverage_type"], "decision": best["decision"], "score": best["score"], "forced": False, "matched_condition": best["condition"], "criteria": best["criteria"] or "No extra criteria"}
                    
                    if carrier == "American Amicable" and product_name == "Senior Choice":
                        amam_sc_result = result
                    else:
                        chart_results.append(result)
                else:
                    chart_results.append({"carrier": carrier, "product": product_name, "coverage_type": info["coverage_type"], "decision": "No Match Found", "score": 0, "forced": False, "matched_condition": "", "criteria": "No matching condition found"})
            except Exception as e:
                file_errors.append(f"{carrier} — {product_name}")
    
    if amam_sc_result and 50 <= age <= 85 and ("copd" in user_text or "diabetes" in user_text) and "oxygen" not in user_text:
        chart_results.insert(0, amam_sc_result)
    elif amam_sc_result:
        chart_results.append(amam_sc_result)
    
    if not chart_results and file_errors:
        embed = discord.Embed(title="❌ File Loading Error", description=f"Age: **{age}** | Input: **{conditions}**", color=0xff0000)
        embed.add_field(name="Missing Files", value="\n".join(file_errors), inline=False)
        return embed, None
    
    chart_results.sort(key=lambda x: (RESULT_PRIORITY.get(x["decision"], 50), -x["score"]))
    
    has_real_option = any(r["decision"] not in BAD_OUTCOMES for r in chart_results)
    
    final_results = chart_results
    if not has_real_option and fallback_results:
        final_results.extend(fallback_results)
    
    final_results.sort(key=lambda x: (RESULT_PRIORITY.get(x["decision"], 50), -x["score"]))
    
    if not final_results:
        embed = discord.Embed(title="❌ No Coverage Available", description=f"Age: **{age}** | Input: **{conditions}**", color=0xff0000)
        return embed, None
    
    best = final_results[0]
    color = DECISION_COLORS.get(best["decision"], 0x7289da)
    emoji = DECISION_EMOJI.get(best["decision"], "❓")
    
    embed = discord.Embed(title=f"{emoji} UNDERWRITING RESULT", color=color)
    embed.add_field(name="🎯 Client Info", value=f"**Age:** {age}\n**Condition:** {conditions}", inline=False)
    embed.add_field(name="🏆 BEST FIT", value=f"**{best['carrier']}** → **{best['product']}**\n{best['coverage_type']}\n\n**Decision:** `{best['decision']}`", inline=False)
    embed.add_field(name="📝 Details", value=best['criteria'], inline=False)
    
    options_text = ""
    for i, r in enumerate(final_results[:5], 1):
        opt_emoji = DECISION_EMOJI.get(r["decision"], "❓")
        options_text += f"{i}. {opt_emoji} **{r['carrier']}** - {r['product']}: `{r['decision']}`\n"
    if len(final_results) > 5:
        options_text += f"\n... and {len(final_results) - 5} more option(s)"
    
    embed.add_field(name="📊 All Options", value=options_text, inline=False)
    embed.set_footer(text=f"UW Bot v2.0 | {len(final_results)} total options")
    
    return embed, None

@bot.tree.command(name="uw", description="Check underwriting eligibility")
@app_commands.describe(age="Client age (e.g., 65)", conditions="Health condition(s) (e.g., COPD)")
async def slash_uw(interaction, age: int, conditions: str):
    await interaction.response.defer()
    embed, _ = await process_uw_query(age, conditions)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="carriers", description="View all carriers and products")
async def slash_carriers(interaction):
    embed = discord.Embed(title="🏢 Available Carriers & Products", color=0x2b82c6, description="Complete product lineup across all carriers")
    for carrier, products in PRODUCTS.items():
        product_list = ", ".join([f"`{p}`" for p in products.keys()])
        embed.add_field(name=f"📌 {carrier}", value=product_list, inline=False)
    embed.set_footer(text=f"Total: {sum(len(p) for p in PRODUCTS.values())} products")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="conditions", description="View all supported health conditions")
async def slash_conditions(interaction):
    await interaction.response.defer()
    conds = load_all_conditions()
    embed = discord.Embed(title="🏥 Supported Health Conditions", color=0x9370db, description=f"Database of {len(conds)} underwriting conditions")
    cond_text = "\n".join([f"• {c}" for c in conds[:40]])
    embed.add_field(name="Conditions (Sample)", value=cond_text, inline=False)
    if len(conds) > 40:
        embed.add_field(name="More", value=f"... and **{len(conds) - 40}** additional conditions", inline=False)
    embed.set_footer(text=f"Showing 1-40 of {len(conds)} total")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="help", description="Get help with bot commands")
async def slash_help(interaction):
    embed = discord.Embed(title="📖 UW Bot Help", color=0xf0a000, description="Master your underwriting workflow")
    embed.add_field(name="/uw <age> <conditions>", value="**Check eligibility across all carriers**\nExample: `/uw 65 COPD`\nGet instant underwriting decisions with carrier recommendations", inline=False)
    embed.add_field(name="/carriers", value="**View all available carriers and products**\nBrowse the complete product lineup", inline=False)
    embed.add_field(name="/conditions", value="**See all supported health conditions**\nSearch the underwriting database", inline=False)
    embed.add_field(name="💡 Tips", value="• Enter conditions naturally (case-insensitive)\n• Combine multiple conditions: `/uw 65 COPD diabetes`\n• Results show best fit first, ranked by priority", inline=False)
    embed.set_footer(text="UW Bot v2.0 | For assistance, contact your team lead")
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
