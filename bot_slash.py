import csv
import os
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")

print("TOKEN:", TOKEN)
print("LENGTH:", len(TOKEN) if TOKEN else 0)
print("STARTS WITH:", TOKEN[:5] if TOKEN else "None")

PRODUCTS = {
    "American Amicable": {
        "Senior Choice": {
            "coverage_type": "Whole Life",
            "min_age": 50,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - AMAM SC.csv"
        },
        "Family Choice": {
            "coverage_type": "Whole Life",
            "min_age": 0,
            "max_age": 49,
            "csv_file": "Carrier Condition Sheet - AMAM FC.csv"
        }
    },
    "Mutual of Omaha": {
        "Living Promise": {
            "coverage_type": "Whole Life",
            "min_age": 45,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - MOO LP.csv"
        }
    },
    "AIG": {
        "SIWL": {
            "coverage_type": "Whole Life",
            "min_age": 0,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - AIG SIWL.csv"
        },
        "GIWL": {
            "coverage_type": "Guaranteed Issue Whole Life",
            "min_age": 50,
            "max_age": 80,
            "special_case": "fallback"
        }
    },
    "Americo": {
        "Eagle Select": {
            "coverage_type": "Whole Life",
            "min_age": 40,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - AMERICO.csv"
        }
    }
}

RESULT_PRIORITY = {
    "Immediate": 1,
    "Level": 1,
    "Allowed": 1,
    "Eagle Select 1": 1,
    "Graded": 2,
    "Eagle Select 2": 2,
    "Eagle Select 2 Non-nicotine": 2,
    "Eagle Select 2 Nicotine": 2,
    "ROP": 3,
    "Return of Premium": 3,
    "Eagle Select 3": 3,
    "Guaranteed Issue Fallback": 4,
    "Decline": 99,
    "DECLINE": 99,
    "No Coverage": 99,
    "No Match Found": 100
}

BAD_OUTCOMES = {"Decline", "DECLINE", "No Coverage", "No Match Found"}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def load_rules(file_path):
    rules = []
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean_row = {}
            for k, v in row.items():
                key = k.strip() if isinstance(k, str) else k
                val = v.strip() if isinstance(v, str) else v
                clean_row[key] = val

            condition = clean_row.get("CONDITION", "")
            criteria = clean_row.get("CRITERIA", "")
            decision = clean_row.get("PLAN TO APPLY FOR", "") or clean_row.get("DECISION", "")

            if condition and decision:
                rules.append({
                    "condition": condition.strip(),
                    "criteria": criteria.strip(),
                    "decision": decision.strip()
                })
    return rules


def normalize_decision(decision):
    d = decision.strip()
    if d.upper() == "DECLINE":
        return "Decline"
    return d


def split_input_phrases(text):
    text = text.lower().replace("/", " ").replace(",", " ")
    return [w.strip() for w in text.split() if w.strip()]


def match_rule(user_text, rule):
    text = user_text.lower().strip()
    cond = rule["condition"].lower().strip()
    crit = rule["criteria"].lower().strip()
    score = 0
    if text == cond:
        score += 100
    elif cond and cond in text:
        score += 40
    elif text == "copd" and cond == "copd":
        score += 100
    elif text == "diabetes" and cond == "diabetes":
        score += 100
    elif cond.startswith(text + " "):
        score += 5
    text_words = set(split_input_phrases(text))
    cond_words = set(split_input_phrases(cond))
    crit_words = set(split_input_phrases(crit))
    common_cond = text_words & cond_words
    score += len(common_cond) * 8
    common_crit = text_words & crit_words
    score += len(common_crit) * 6
    if crit and len(common_crit) == 0:
        score -= 8
    return score


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Running from folder: {os.getcwd()}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


async def process_uw_query(age: int, conditions: str):
    user_text = conditions.lower().strip()
    chart_results = []
    fallback_results = []
    file_errors = []

    if 50 <= age <= 85 and ("copd" in user_text or "diabetes" in user_text) and "oxygen" not in user_text:
        chart_results.append({
            "carrier": "American Amicable",
            "product": "Senior Choice",
            "coverage_type": "Whole Life",
            "decision": "Immediate",
            "score": 999999,
            "forced": True,
            "matched_condition": "AMAM playbook override",
            "criteria": "COPD and/or diabetes often gets tried with AMAM Immediate first unless stronger negative factors exist."
        })

    for carrier, products in PRODUCTS.items():
        for product_name, info in products.items():
            if not (info["min_age"] <= age <= info["max_age"]):
                continue

            if info.get("special_case") == "fallback":
                fallback_results.append({
                    "carrier": carrier,
                    "product": product_name,
                    "coverage_type": info["coverage_type"],
                    "decision": "Guaranteed Issue Fallback",
                    "score": 1,
                    "forced": False,
                    "matched_condition": "",
                    "criteria": "Use only as last resort after chart-based products come back decline / no coverage / no good match."
                })
                continue

            if (
                carrier == "American Amicable"
                and product_name == "Senior Choice"
                and 50 <= age <= 85
                and ("copd" in user_text or "diabetes" in user_text)
                and "oxygen" not in user_text
            ):
                continue

            csv_file = info.get("csv_file")
            if not csv_file or not os.path.exists(csv_file):
                file_errors.append(f"{carrier} — {product_name} → {csv_file}")
                continue

            try:
                rules = load_rules(csv_file)
            except Exception as e:
                file_errors.append(f"{carrier} — {product_name} → {csv_file} ({str(e)})")
                continue

            matched_rules = []

            for rule in rules:
                score = match_rule(user_text, rule)
                if score > 0:
                    matched_rules.append({
                        "condition": rule["condition"],
                        "criteria": rule["criteria"],
                        "decision": normalize_decision(rule["decision"]),
                        "score": score
                    })

            if matched_rules:
                matched_rules.sort(key=lambda r: (-r["score"], RESULT_PRIORITY.get(r["decision"], 50)))
                best_match = matched_rules[0]

                chart_results.append({
                    "carrier": carrier,
                    "product": product_name,
                    "coverage_type": info["coverage_type"],
                    "decision": best_match["decision"],
                    "score": best_match["score"],
                    "forced": False,
                    "matched_condition": best_match["condition"],
                    "criteria": best_match["criteria"] or "No extra criteria listed."
                })
            else:
                chart_results.append({
                    "carrier": carrier,
                    "product": product_name,
                    "coverage_type": info["coverage_type"],
                    "decision": "No Match Found",
                    "score": 0,
                    "forced": False,
                    "matched_condition": "",
                    "criteria": "No chart row matched this input yet."
                })

    if not chart_results and file_errors:
        error_msg = f"""❌ **Chart files not loading**

**Age:** {age}
**Input:** {conditions}

### Missing / Broken CSV Files
""" + "\n".join([f"• {x}" for x in file_errors])
        return None, error_msg

    chart_results.sort(key=lambda x: (
        0 if x.get("forced") else 1,
        RESULT_PRIORITY.get(x["decision"], 50),
        -x["score"]
    ))

    has_real_non_gi_option = any(r["decision"] not in BAD_OUTCOMES for r in chart_results)

    final_results = list(chart_results)

    if not has_real_non_gi_option:
        final_results.extend(fallback_results)

    final_results.sort(key=lambda x: (
        0 if x.get("forced") else 1,
        RESULT_PRIORITY.get(x["decision"], 50),
        -x["score"]
    ))

    if not final_results:
        error_msg = f"""❌ **No Coverage Available**

**Age:** {age}
**Input:** {conditions}

No eligible coverage was found based on the products currently loaded in the bot.
"""
        return None, error_msg

    best = final_results[0]

    matched_line = ""
    if best.get("matched_condition"):
        matched_line = f"\n• **Matched Condition:** {best['matched_condition']}"

    notes_line = ""

    if file_errors:
        notes_line += "\n\n⚠️ Some product files did not load:\n" + "\n".join([f"• {x}" for x in file_errors])

    all_options = "\n".join([
        f"• **{r['carrier']} — {r['product']}** → **{r['decision']}**"
        for r in final_results
    ])

    embed = discord.Embed(
        title="🩺 UW RESULT",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="Age", value=str(age), inline=True)
    embed.add_field(name="Input", value=conditions, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    embed.add_field(
        name="🏆 Best Fit",
        value=f"""• **Carrier:** {best['carrier']}
- **Product:** {best['product']}
- **Coverage:** {best['coverage_type']}
- **Result:** **{best['decision']}**{matched_line}""",
        inline=False
    )
    
    embed.add_field(
        name="📋 Criteria / Notes",
        value=best['criteria'],
        inline=False
    )
    
    embed.add_field(
        name="📊 All Options",
        value=all_options,
        inline=False
    )
    
    if notes_line:
        embed.add_field(name="⚠️ Warnings", value=notes_line, inline=False)

    return embed, None


@bot.tree.command(
    name="uw",
    description="Check underwriting eligibility for a client"
)
@app_commands.describe(
    age="Client's age (e.g., 65)",
    conditions="Health condition(s) (e.g., COPD, diabetes, heart disease)"
)
async def slash_uw(interaction: discord.Interaction, age: int, conditions: str):
    await interaction.response.defer()
    embed, error_msg = await process_uw_query(age, conditions)
    if error_msg:
        await interaction.followup.send(error_msg)
    else:
        await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="carriers",
    description="List all available carriers and products"
)
async def slash_carriers(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Available Carriers & Products",
        color=discord.Color.green()
    )
    
    for carrier, products in PRODUCTS.items():
        product_list = ", ".join(products.keys())
        embed.add_field(
            name=carrier,
            value=product_list,
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="conditions",
    description="List all supported health conditions"
)
async def slash_conditions(interaction: discord.Interaction):
    await interaction.response.defer()
    
    all_conditions = set()
    
    for carrier, products in PRODUCTS.items():
        for product_name, info in products.items():
            csv_file = info.get("csv_file")
            if csv_file and os.path.exists(csv_file):
                try:
                    rules = load_rules(csv_file)
                    for rule in rules:
                        all_conditions.add(rule["condition"])
                except:
                    pass
    
    sorted_conditions = sorted(list(all_conditions))
    
    chunk_size = 20
    chunks = [sorted_conditions[i:i+chunk_size] for i in range(0, len(sorted_conditions), chunk_size)]
    
    embed = discord.Embed(
        title=f"🏥 Supported Conditions ({len(sorted_conditions)} total)",
        color=discord.Color.purple()
    )
    
    for idx, chunk in enumerate(chunks):
        embed.add_field(
            name=f"Conditions {idx*chunk_size + 1}-{min((idx+1)*chunk_size, len(sorted_conditions))}",
            value="\n".join(chunk),
            inline=False
        )
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="help",
    description="Show bot commands and usage"
)
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 UW Bot Help",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="/uw <age> <conditions>",
        value="Check underwriting eligibility\n**Example:** `/uw 65 COPD`",
        inline=False
    )
    
    embed.add_field(
        name="/carriers",
        value="List all available carriers and products",
        inline=False
    )
    
    embed.add_field(
        name="/conditions",
        value="List all supported health conditions",
        inline=False
    )
    
    embed.add_field(
        name="/help",
        value="Show this message",
        inline=False
    )
    
    embed.set_footer(text="Tip: You can enter conditions with or without capitalization")
    
    await interaction.response.send_message(embed=embed)


@bot.command()
async def uw(ctx, age: int, *, conditions: str):
    embed, error_msg = await process_uw_query(age, conditions)
    if error_msg:
        await ctx.send(error_msg)
    else:
        await ctx.send(embed=embed)


bot.run(TOKEN)import csv
import os
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")

print("TOKEN:", TOKEN)
print("LENGTH:", len(TOKEN) if TOKEN else 0)
print("STARTS WITH:", TOKEN[:5] if TOKEN else "None")

PRODUCTS = {
    "American Amicable": {
        "Senior Choice": {
            "coverage_type": "Whole Life",
            "min_age": 50,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - AMAM SC.csv"
        },
        "Family Choice": {
            "coverage_type": "Whole Life",
            "min_age": 0,
            "max_age": 49,
            "csv_file": "Carrier Condition Sheet - AMAM FC.csv"
        }
    },
    "Mutual of Omaha": {
        "Living Promise": {
            "coverage_type": "Whole Life",
            "min_age": 45,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - MOO LP.csv"
        }
    },
    "AIG": {
        "SIWL": {
            "coverage_type": "Whole Life",
            "min_age": 0,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - AIG SIWL.csv"
        },
        "GIWL": {
            "coverage_type": "Guaranteed Issue Whole Life",
            "min_age": 50,
            "max_age": 80,
            "special_case": "fallback"
        }
    },
    "Americo": {
        "Eagle Select": {
            "coverage_type": "Whole Life",
            "min_age": 40,
            "max_age": 85,
            "csv_file": "Carrier Condition Sheet - AMERICO.csv"
        }
    }
}

RESULT_PRIORITY = {
    "Immediate": 1,
    "Level": 1,
    "Allowed": 1,
    "Eagle Select 1": 1,
    "Graded": 2,
    "Eagle Select 2": 2,
    "Eagle Select 2 Non-nicotine": 2,
    "Eagle Select 2 Nicotine": 2,
    "ROP": 3,
    "Return of Premium": 3,
    "Eagle Select 3": 3,
    "Guaranteed Issue Fallback": 4,
    "Decline": 99,
    "DECLINE": 99,
    "No Coverage": 99,
    "No Match Found": 100
}

BAD_OUTCOMES = {"Decline", "DECLINE", "No Coverage", "No Match Found"}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def load_rules(file_path):
    rules = []
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean_row = {}
            for k, v in row.items():
                key = k.strip() if isinstance(k, str) else k
                val = v.strip() if isinstance(v, str) else v
                clean_row[key] = val

            condition = clean_row.get("CONDITION", "")
            criteria = clean_row.get("CRITERIA", "")
            decision = clean_row.get("PLAN TO APPLY FOR", "") or clean_row.get("DECISION", "")

            if condition and decision:
                rules.append({
                    "condition": condition.strip(),
                    "criteria": criteria.strip(),
                    "decision": decision.strip()
                })
    return rules


def normalize_decision(decision):
    d = decision.strip()
    if d.upper() == "DECLINE":
        return "Decline"
    return d


def split_input_phrases(text):
    text = text.lower().replace("/", " ").replace(",", " ")
    return [w.strip() for w in text.split() if w.strip()]


def match_rule(user_text, rule):
    text = user_text.lower().strip()
    cond = rule["condition"].lower().strip()
    crit = rule["criteria"].lower().strip()
    score = 0
    if text == cond:
        score += 100
    elif cond and cond in text:
        score += 40
    elif text == "copd" and cond == "copd":
        score += 100
    elif text == "diabetes" and cond == "diabetes":
        score += 100
    elif cond.startswith(text + " "):
        score += 5
    text_words = set(split_input_phrases(text))
    cond_words = set(split_input_phrases(cond))
    crit_words = set(split_input_phrases(crit))
    common_cond = text_words & cond_words
    score += len(common_cond) * 8
    common_crit = text_words & crit_words
    score += len(common_crit) * 6
    if crit and len(common_crit) == 0:
        score -= 8
    return score


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print(f"Running from folder: {os.getcwd()}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


async def process_uw_query(age: int, conditions: str):
    user_text = conditions.lower().strip()
    chart_results = []
    fallback_results = []
    file_errors = []

    if 50 <= age <= 85 and ("copd" in user_text or "diabetes" in user_text) and "oxygen" not in user_text:
        chart_results.append({
            "carrier": "American Amicable",
            "product": "Senior Choice",
            "coverage_type": "Whole Life",
            "decision": "Immediate",
            "score": 999999,
            "forced": True,
            "matched_condition": "AMAM playbook override",
            "criteria": "COPD and/or diabetes often gets tried with AMAM Immediate first unless stronger negative factors exist."
        })

    for carrier, products in PRODUCTS.items():
        for product_name, info in products.items():
            if not (info["min_age"] <= age <= info["max_age"]):
                continue

            if info.get("special_case") == "fallback":
                fallback_results.append({
                    "carrier": carrier,
                    "product": product_name,
                    "coverage_type": info["coverage_type"],
                    "decision": "Guaranteed Issue Fallback",
                    "score": 1,
                    "forced": False,
                    "matched_condition": "",
                    "criteria": "Use only as last resort after chart-based products come back decline / no coverage / no good match."
                })
                continue

            if (
                carrier == "American Amicable"
                and product_name == "Senior Choice"
                and 50 <= age <= 85
                and ("copd" in user_text or "diabetes" in user_text)
                and "oxygen" not in user_text
            ):
                continue

            csv_file = info.get("csv_file")
            if not csv_file or not os.path.exists(csv_file):
                file_errors.append(f"{carrier} — {product_name} → {csv_file}")
                continue

            try:
                rules = load_rules(csv_file)
            except Exception as e:
                file_errors.append(f"{carrier} — {product_name} → {csv_file} ({str(e)})")
                continue

            matched_rules = []

            for rule in rules:
                score = match_rule(user_text, rule)
                if score > 0:
                    matched_rules.append({
                        "condition": rule["condition"],
                        "criteria": rule["criteria"],
                        "decision": normalize_decision(rule["decision"]),
                        "score": score
                    })

            if matched_rules:
                matched_rules.sort(key=lambda r: (-r["score"], RESULT_PRIORITY.get(r["decision"], 50)))
                best_match = matched_rules[0]

                chart_results.append({
                    "carrier": carrier,
                    "product": product_name,
                    "coverage_type": info["coverage_type"],
                    "decision": best_match["decision"],
                    "score": best_match["score"],
                    "forced": False,
                    "matched_condition": best_match["condition"],
                    "criteria": best_match["criteria"] or "No extra criteria listed."
                })
            else:
                chart_results.append({
                    "carrier": carrier,
                    "product": product_name,
                    "coverage_type": info["coverage_type"],
                    "decision": "No Match Found",
                    "score": 0,
                    "forced": False,
                    "matched_condition": "",
                    "criteria": "No chart row matched this input yet."
                })

    if not chart_results and file_errors:
        error_msg = f"""❌ **Chart files not loading**

**Age:** {age}
**Input:** {conditions}

### Missing / Broken CSV Files
""" + "\n".join([f"• {x}" for x in file_errors])
        return None, error_msg

    chart_results.sort(key=lambda x: (
        0 if x.get("forced") else 1,
        RESULT_PRIORITY.get(x["decision"], 50),
        -x["score"]
    ))

    has_real_non_gi_option = any(r["decision"] not in BAD_OUTCOMES for r in chart_results)

    final_results = list(chart_results)

    if not has_real_non_gi_option:
        final_results.extend(fallback_results)

    final_results.sort(key=lambda x: (
        0 if x.get("forced") else 1,
        RESULT_PRIORITY.get(x["decision"], 50),
        -x["score"]
    ))

    if not final_results:
        error_msg = f"""❌ **No Coverage Available**

**Age:** {age}
**Input:** {conditions}

No eligible coverage was found based on the products currently loaded in the bot.
"""
        return None, error_msg

    best = final_results[0]

    matched_line = ""
    if best.get("matched_condition"):
        matched_line = f"\n• **Matched Condition:** {best['matched_condition']}"

    notes_line = ""

    if file_errors:
        notes_line += "\n\n⚠️ Some product files did not load:\n" + "\n".join([f"• {x}" for x in file_errors])

    all_options = "\n".join([
        f"• **{r['carrier']} — {r['product']}** → **{r['decision']}**"
        for r in final_results
    ])

    embed = discord.Embed(
        title="🩺 UW RESULT",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="Age", value=str(age), inline=True)
    embed.add_field(name="Input", value=conditions, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    embed.add_field(
        name="🏆 Best Fit",
        value=f"""• **Carrier:** {best['carrier']}
- **Product:** {best['product']}
- **Coverage:** {best['coverage_type']}
- **Result:** **{best['decision']}**{matched_line}""",
        inline=False
    )
    
    embed.add_field(
        name="📋 Criteria / Notes",
        value=best['criteria'],
        inline=False
    )
    
    embed.add_field(
        name="📊 All Options",
        value=all_options,
        inline=False
    )
    
    if notes_line:
        embed.add_field(name="⚠️ Warnings", value=notes_line, inline=False)

    return embed, None


@bot.tree.command(
    name="uw",
    description="Check underwriting eligibility for a client"
)
@app_commands.describe(
    age="Client's age (e.g., 65)",
    conditions="Health condition(s) (e.g., COPD, diabetes, heart disease)"
)
async def slash_uw(interaction: discord.Interaction, age: int, conditions: str):
    await interaction.response.defer()
    embed, error_msg = await process_uw_query(age, conditions)
    if error_msg:
        await interaction.followup.send(error_msg)
    else:
        await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="carriers",
    description="List all available carriers and products"
)
async def slash_carriers(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Available Carriers & Products",
        color=discord.Color.green()
    )
    
    for carrier, products in PRODUCTS.items():
        product_list = ", ".join(products.keys())
        embed.add_field(
            name=carrier,
            value=product_list,
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="conditions",
    description="List all supported health conditions"
)
async def slash_conditions(interaction: discord.Interaction):
    await interaction.response.defer()
    
    all_conditions = set()
    
    for carrier, products in PRODUCTS.items():
        for product_name, info in products.items():
            csv_file = info.get("csv_file")
            if csv_file and os.path.exists(csv_file):
                try:
                    rules = load_rules(csv_file)
                    for rule in rules:
                        all_conditions.add(rule["condition"])
                except:
                    pass
    
    sorted_conditions = sorted(list(all_conditions))
    
    chunk_size = 20
    chunks = [sorted_conditions[i:i+chunk_size] for i in range(0, len(sorted_conditions), chunk_size)]
    
    embed = discord.Embed(
        title=f"🏥 Supported Conditions ({len(sorted_conditions)} total)",
        color=discord.Color.purple()
    )
    
    for idx, chunk in enumerate(chunks):
        embed.add_field(
            name=f"Conditions {idx*chunk_size + 1}-{min((idx+1)*chunk_size, len(sorted_conditions))}",
            value="\n".join(chunk),
            inline=False
        )
    
    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="help",
    description="Show bot commands and usage"
)
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 UW Bot Help",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="/uw <age> <conditions>",
        value="Check underwriting eligibility\n**Example:** `/uw 65 COPD`",
        inline=False
    )
    
    embed.add_field(
        name="/carriers",
        value="List all available carriers and products",
        inline=False
    )
    
    embed.add_field(
        name="/conditions",
        value="List all supported health conditions",
        inline=False
    )
    
    embed.add_field(
        name="/help",
        value="Show this message",
        inline=False
    )
    
    embed.set_footer(text="Tip: You can enter conditions with or without capitalization")
    
    await interaction.response.send_message(embed=embed)


@bot.command()
async def uw(ctx, age: int, *, conditions: str):
    embed, error_msg = await process_uw_query(age, conditions)
    if error_msg:
        await ctx.send(error_msg)
    else:
        await ctx.send(embed=embed)


bot.run(TOKEN)
