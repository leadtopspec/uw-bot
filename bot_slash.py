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

PLAYBOOK = {
    "oxygen": {"priority": 1, "best": ("AIG", "GIWL", "Guaranteed Issue")},
    "copd": {"priority": 2, "best": ("American Amicable", "Senior Choice", "Immediate"), "backup": [("Americo", "Eagle Select", "Level"), ("Mutual of Omaha", "Living Promise", "Graded")]},
    "diabetes": {"priority": 3, "best": ("Americo", "Eagle Select", "Level"), "backup": [("American Amicable", "Senior Choice", "Immediate"), ("Mutual of Omaha", "Living Promise", "Graded")]},
    "stroke": {"priority": 4, "best": ("Americo", "Eagle Select", "Level"), "backup": [("Mutual of Omaha", "Living Promise", "Graded"), ("American Amicable", "Senior Choice", "Graded")]},
    "heart attack": {"priority": 5, "best": ("Americo", "Eagle Select", "Level"), "backup": [("American Amicable", "Senior Choice", "Graded"), ("AIG", "SIWL", "Graded")]},
    "kidney failure": {"priority": 6, "best": ("Americo", "Eagle Select", "Level"), "backup": [("American Amicable", "Senior Choice", "Graded"), ("AIG", "SIWL", "Graded")]},
    "dialysis": {"priority": 7, "best": ("American Amicable", "Senior Choice", "Graded"), "backup": [("AIG", "SIWL", "Graded"), ("AIG", "GIWL", "Guaranteed Issue")]},
    "hiv": {"priority": 8, "best": ("AIG", "GIWL", "Guaranteed Issue")},
    "aids": {"priority": 8, "best": ("AIG", "GIWL", "Guaranteed Issue")},
}

COMBO_PLAYBOOK = {
    "copd diabetes": ("American Amicable", "Senior Choice", "Immediate"),
    "diabetes copd": ("American Amicable", "Senior Choice", "Immediate"),
    "stroke copd": ("American Amicable", "Senior Choice", "Graded"),
    "copd stroke": ("American Amicable", "Senior Choice", "Graded"),
    "stroke diabetes": ("Mutual of Omaha", "Living Promise", "Graded"),
    "diabetes stroke": ("Mutual of Omaha", "Living Promise", "Graded"),
    "heart attack stroke": ("American Amicable", "Senior Choice", "Graded"),
    "stroke heart attack": ("American Amicable", "Senior Choice", "Graded"),
}

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

def get_playbook_result(conditions):
    user_text = conditions.lower().strip()
    
    for combo, (carrier, product, decision) in COMBO_PLAYBOOK.items():
        if all(word in user_text for word in combo.split()):
            return carrier, product, decision
    
    for cond_key, playbook in PLAYBOOK.items():
        if cond_key in user_text:
            return playbook["best"][0], playbook["best"][1], playbook["best"][2]
    
    return None

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
    
    playbook_result = get_playbook_result(user_text)
    if playbook_result:
        carrier, product, decision = playbook_result
        if (carrier, product) in [("American Amicable", "Senior Choice"), ("American Amicable", "Family Choice")] or PRODUCTS[carrier][product]["min_age"] <= age <= PRODUCTS[carrier][product]["max_age"]:
            best = {
                "carrier": carrier,
                "product": product,
                "coverage_type": PRODUCTS[carrier][product]["coverage_type"],
                "decision": decision,
                "criteria": f"Playbook recommended for {conditions}"
            }
            
            embed = discord.Embed(title=f"{DECISION_EMOJI.get(decision, '❓')} UNDERWRITING RESULT", color=DECISION_COLORS.get(decision, 0x7289da))
            embed.add_field(name="🎯 Client Info", value=f"**Age:** {age}\n**Condition:** {conditions}", inline=False)
            embed.add_field(name="🏆 BEST FIT", value=f"**{best['carrier']}** → **{best['product']}**\n{best['coverage_type']}\n\n**Decision:** `{best['decision']}`", inline=False)
            embed.add_field(name="📝 Details", value=best['criteria'], inline=False)
            embed.set_footer(text="UW Bot v2.0 | Playbook Recommendation")
            return embed, None
    
    embed = discord.Embed(title="❓ No Playbook Match", description=f"Age: **{age}** | Condition: **{conditions}**\nPlease check CSV rules manually.", color=0x808080)
    return embed, None

@bot.tree.command(name="uw", description="Check underwriting eligibility")
@app_commands.describe(age="Client age (e.g., 65)", conditions="Health condition(s) (e.g., COPD, Diabetes)")
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
    embed.add_field(name="💡 Tips", value="• Enter conditions naturally (case-insensitive)\n• Combine multiple conditions: `/uw 65 COPD Diabetes`\n• Playbook automatically routes to best carrier", inline=False)
    embed.set_footer(text="UW Bot v2.0 | For assistance, contact your team lead")
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
