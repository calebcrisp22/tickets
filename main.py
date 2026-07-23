import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
import io
from collections import defaultdict

# ==============================================
# CONFIG & FILES
# ==============================================

CONFIG_FILE = "config.json"
BLACKLIST_FILE = "blacklist.txt"
WARNINGS_FILE = "warnings.json"
TICKET_PANELS_FILE = "ticket_panels.json"
VOUCHES_FILE = "vouches.json"
GIVEAWAYS_FILE = "giveaways.json"

if not os.path.exists(CONFIG_FILE):
    print("❌ config.json not found! Create it first.")
    exit(1)

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["TOKEN"]
TICKET_CATEGORY_ID = config.get("TICKET_CATEGORY_ID", 0)
SUPPORT_ROLE_ID = config.get("SUPPORT_ROLE_ID", 0)
TRANSCRIPT_CHANNEL_ID = config.get("transcript_channel_id", None)
WELCOME_CHANNEL_ID = config.get("welcome_channel_id", None)
BLACKLIST_LOG_CHANNEL_ID = config.get("blacklist_log_channel_id", None)
MOD_LOG_CHANNEL_ID = config.get("mod_log_channel_id", None)
ANTI_NUKE_LOG_CHANNEL_ID = config.get("anti_nuke_log_channel_id", None)
ANNOUNCE_LOG_CHANNEL_ID = config.get("announce_log_channel_id", None)

WELCOME_MESSAGE = config.get("welcome_message", "Welcome {user}!
Developed by LiaMae")

MAIN_COLOR = int(config.get("EMBED_COLOR", "#5865F2").replace("#", ""), 16)
SUCCESS_COLOR = int(config.get("SUCCESS_COLOR", "#57F287").replace("#", ""), 16)
ERROR_COLOR = int(config.get("ERROR_COLOR", "#ED4245").replace("#", ""), 16)
FOOTER_TEXT = config.get("FOOTER_TEXT", "Developed by LiaMae")

STATUS_CFG = config.get("STATUS", {})
STATUS_ENABLED = STATUS_CFG.get("enabled", True)
STATUS_INTERVAL = STATUS_CFG.get("interval_seconds", 45)
STATUS_RANDOM = STATUS_CFG.get("random_order", True)
STATUS_ACTIVITIES = STATUS_CFG.get("activities", [])

PANEL_CFG = config.get("TICKET_PANEL", {})
PANEL_TITLE = PANEL_CFG.get("title", "Developed by LiaMae • Create a Ticket")
PANEL_DESC = PANEL_CFG.get("description", "Developed by LiaMae Support. To ensure your request is handled by the right specialist as quickly as possible, please select the most relevant category from the options listed below.")
PANEL_BANNER = PANEL_CFG.get("banner_url")

TICKET_TYPES = PANEL_CFG.get("ticket_types", [])

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.invites = True
intents.guilds = True
intents.moderation = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

ticket_panels = {}
vouches = {}
blacklisted_patterns = []
warnings = {}
giveaways = {}
open_tickets = {}   # channel_id : {"guild_id": int, "user_id": int, "feedback_given": bool}

NUKE_THRESHOLD = 5
NUKE_WINDOW = 10
nuke_actions = defaultdict(list)

# ==============================================
# LOAD DATA
# ==============================================

def load_data():
    global ticket_panels, vouches, blacklisted_patterns, warnings, giveaways
    try:
        if os.path.exists(TICKET_PANELS_FILE):
            with open(TICKET_PANELS_FILE, "r") as f:
                ticket_panels = json.load(f)
        if os.path.exists(VOUCHES_FILE):
            with open(VOUCHES_FILE, "r") as f:
                raw = json.load(f)
                vouches = {int(g): {int(u): v for u, v in users.items()} for g, users in raw.items()}
        if os.path.exists(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                blacklisted_patterns = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if os.path.exists(WARNINGS_FILE):
            with open(WARNINGS_FILE, "r") as f:
                warnings = json.load(f)
        if os.path.exists(GIVEAWAYS_FILE):
            with open(GIVEAWAYS_FILE, "r") as f:
                giveaways = json.load(f)
        print("Data loaded successfully!")
    except Exception as e:
        print(f"Load error: {e}")

def save_data():
    try:
        with open(TICKET_PANELS_FILE, "w") as f:
            json.dump(ticket_panels, f, indent=2)
        with open(VOUCHES_FILE, "w") as f:
            json.dump(vouches, f, indent=2)
        with open(WARNINGS_FILE, "w") as f:
            json.dump(warnings, f, indent=2)
        with open(GIVEAWAYS_FILE, "w") as f:
            json.dump(giveaways, f, indent=2)
    except Exception as e:
        print(f"Save error: {e}")

# ==============================================
# EMBED BUILDER
# ==============================================

def create_embed(title=None, description=None, color=MAIN_COLOR, guild=None):
    e = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    e.set_footer(text=FOOTER_TEXT)
    if guild and guild.icon:
        e.set_thumbnail(url=guild.icon.url)
    return e

# ==============================================
# LOGGING HELPER
# ==============================================

async def send_log(guild: discord.Guild, log_type: str, embed: discord.Embed):
    channel_id_keys = {
        "transcript": "transcript_channel_id",
        "blacklist": "blacklist_log_channel_id",
        "mod": "mod_log_channel_id",
        "anti_nuke": "anti_nuke_log_channel_id",
        "announce": "announce_log_channel_id"
    }

    key = channel_id_keys.get(log_type)
    if not key:
        print(f"[LOG] Unknown log type: {log_type}")
        return

    channel_id = config.get(key)
    if not channel_id:
        print(f"[LOG] No channel set for {log_type}")
        return

    channel = guild.get_channel(channel_id)
    if not channel:
        print(f"[LOG] Channel {channel_id} not found for {log_type}")
        return

    try:
        await channel.send(embed=embed)
        print(f"[LOG] Sent {log_type} log to {channel.name}")
    except Exception as e:
        print(f"[LOG ERROR] {log_type}: {e}")

# ==============================================
# WELCOMER
# ==============================================

@bot.event
async def on_member_join(member: discord.Member):
    if not WELCOME_CHANNEL_ID:
        print("[WELCOME] No welcome_channel_id set")
        return

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        print(f"[WELCOME] Channel {WELCOME_CHANNEL_ID} not found")
        return

    try:
        # Die Embed vorbereiten
        msg_text = WELCOME_MESSAGE.format(user=member.mention)

        embed = create_embed(
            title="Developed by LiaMae",
            description=msg_text,
            color=MAIN_COLOR,
            guild=member.guild
        )

        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        if member.guild.banner:
            embed.set_image(url=member.guild.banner.url)

        embed.set_footer(text=FOOTER_TEXT)

        # Eine Nachricht: Mention oben + Embed darunter
        await channel.send(content=member.mention, embed=embed)
        print(f"[WELCOME] Sent single message (@user + embed) to {member} in {channel.name}")

    except discord.Forbidden:
        print("[WELCOME] Missing permissions in channel")
    except Exception as e:
        print(f"[WELCOME ERROR] {e}")


# ==============================================
# TICKET PANEL FUNCTIONS
# ==============================================

async def get_panel_embed(guild: discord.Guild):
    e = create_embed(title=PANEL_TITLE, description=PANEL_DESC, guild=guild)
    if PANEL_BANNER: e.set_image(url=PANEL_BANNER)
    return e


async def update_panel(guild):
    gid = str(guild.id)
    if gid not in ticket_panels: return
    try:
        data = ticket_panels[gid]
        ch = guild.get_channel(int(data["channel_id"]))
        msg = await ch.fetch_message(int(data["message_id"]))
        await msg.edit(embed=await get_panel_embed(guild), view=TicketPanelView())
    except Exception as e:
        print(f"Update panel error: {e}")


async def refresh_all_panels():
    refreshed = 0
    to_remove = []

    for guild_id_str, data in list(ticket_panels.items()):
        try:
            guild_id = int(guild_id_str)
            guild = bot.get_guild(guild_id)
            if not guild:
                to_remove.append(guild_id_str)
                continue

            channel = guild.get_channel(int(data["channel_id"]))
            if not channel:
                to_remove.append(guild_id_str)
                continue

            message = await channel.fetch_message(int(data["message_id"]))
            if not message:
                to_remove.append(guild_id_str)
                continue

            await message.edit(embed=await get_panel_embed(guild), view=TicketPanelView())
            refreshed += 1

        except discord.NotFound:
            to_remove.append(guild_id_str)
        except Exception as e:
            print(f"Refresh error in guild {guild_id_str}: {e}")

    for gid in to_remove:
        if gid in ticket_panels:
            del ticket_panels[gid]

    if to_remove:
        save_data()

    print(f"Refreshed {refreshed} ticket panels")


class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for t in TICKET_TYPES:
            if not isinstance(t, dict):
                print(f"[WARN] Invalid ticket type: {t}")
                continue
            label = t.get("label")
            value = t.get("value")
            if not label or not value:
                print(f"[WARN] Skipping invalid ticket type (missing label/value): {t}")
                continue
            options.append(discord.SelectOption(
                label=label,
                value=value,
                description=t.get("description"),
                emoji=t.get("emoji")
            ))
        super().__init__(
            placeholder="Select ticket category...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_category_select"
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        selected = next((t for t in TICKET_TYPES if t.get("value") == value), None)
        if not selected:
            return await interaction.response.send_message(
                embed=create_embed(title="Error", description="Category not found", color=ERROR_COLOR, guild=interaction.guild), 
                ephemeral=True
            )

        await interaction.response.defer()

        category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
        if not category:
            return await interaction.followup.send(
                embed=create_embed(title="Error", description="Ticket category not found", color=ERROR_COLOR, guild=interaction.guild), 
                ephemeral=True
            )

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True),
        }

        support_role = interaction.guild.get_role(SUPPORT_ROLE_ID)
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True)

        channel_name = f"ticket-{value}-{interaction.user.name.lower()[:12]}"
        
        ticket_channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=f"Ticket | {selected.get('label', value)} | Created by {interaction.user.id}",
            overwrites=overwrites
        )

        opening_desc = selected.get("opening_embed_description", "Hello {user}!\n\n**Please describe your issue in detail:**\n• What happened?\n• Any IDs / usernames?\n• Screenshots if possible\n\nSupport will be with you soon! ⏳")
        opening_desc = opening_desc.format(user=interaction.user.mention)

        welcome = create_embed(
            title=f"🎟️ {selected.get('label', value)} Ticket",
            description=opening_desc,
            guild=interaction.guild
        )

        # Close Button mit richtiger View
        view = CloseMenu()

        await ticket_channel.send(
            content=f"{interaction.user.mention} {support_role.mention if support_role else ''}",
            embed=welcome,
            view=view
        )

        # Ticket tracking
        open_tickets[ticket_channel.id] = {
            "guild_id": interaction.guild.id,
            "user_id": interaction.user.id,
            "feedback_given": False
        }

        bot.loop.create_task(auto_feedback_task(ticket_channel.id))

        await interaction.followup.send(
            embed=create_embed(description=f"Ticket created → {ticket_channel.mention} 🚀", color=SUCCESS_COLOR, guild=interaction.guild), 
            ephemeral=True
        )
        await update_panel(interaction.guild)



class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# ────────────────────────────────────────────────
# TRANSCRIPT
# ────────────────────────────────────────────────
async def generate_transcript(channel: discord.TextChannel):
    lines = []
    lines.append(f"📄 Ticket Transcript")
    lines.append(f"Server: {channel.guild.name}")
    lines.append(f"Channel: {channel.name}")
    lines.append(f"Channel ID: {channel.id}")
    lines.append(f"Closed at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("=" * 90 + "\n")

    async for msg in channel.history(limit=2000, oldest_first=True):
        ts = msg.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        author = msg.author.display_name if msg.author else "Unknown"
        content = msg.content or "[No content]"

        if msg.attachments:
            content += f" [📎 {len(msg.attachments)} attachments]"

        lines.append(f"[{ts}] {author}: {content}")

        for embed in msg.embeds:
            if embed.title or embed.description:
                lines.append(f"[{ts}] EMBED: {embed.title or ''} | {embed.description or ''}")

    lines.append("\n" + "=" * 90)
    lines.append("End of Transcript")

    text = "\n".join(lines)
    
    # Sichere Datei mit BytesIO
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel.name)[:30]
    filename = f"transcript-{safe_name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.txt"
    
    return discord.File(io.BytesIO(text.encode("utf-8")), filename=filename)
    return "\n".join(transcript)

# ==============================================
# CLOSE MENU - Final Working Version
# ==============================================

class CloseMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Final Close & Delete", style=discord.ButtonStyle.red, emoji="✅", custom_id="close_ticket")
    async def final_close(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.defer(ephemeral=True)
        await i.followup.send("📝 Creating transcript...", ephemeral=True)

        # Transcript erstellen
        try:
            transcript_file = await generate_transcript(i.channel)
        except Exception as e:
            print(f"[Transcript Error] {e}")
            return await i.followup.send("❌ Could not create transcript.", ephemeral=True)

        # 1. In Log Channel senden
        if TRANSCRIPT_CHANNEL_ID:
            log_channel = i.guild.get_channel(TRANSCRIPT_CHANNEL_ID)
            if log_channel:
                try:
                    await log_channel.send(
                        f"**Ticket Closed** • `{i.channel.name}`\nClosed by {i.user.mention}",
                        file=transcript_file
                    )
                except Exception as e:
                    print(f"[Log Error] {e}")

        # 2. Per DM an Ticket Ersteller
        creator = None
        async for msg in i.channel.history(limit=100, oldest_first=True):
            if msg.author != i.guild.me and not msg.author.bot:
                creator = msg.author
                break

        dm_sent = False
        if creator:
            try:
                transcript_file2 = await generate_transcript(i.channel)
                await creator.send(
                    f"**Your ticket `{i.channel.name}` has been closed.**\n"
                    f"Here is your full transcript from **{i.guild.name}**:",
                    file=transcript_file2
                )
                dm_sent = True
            except:
                print(f"[DM] Failed to send transcript to {creator}")

        # Status Nachricht
        status = "✅ Ticket successfully closed and deleted!\n"
        if dm_sent:
            status += "• Transcript sent via DM\n"
        else:
            status += "• Could not send DM (user has DMs disabled)\n"
        status += "• Transcript saved in log channel"

        await i.followup.send(status, ephemeral=True)

        # Ticket löschen
        await asyncio.sleep(3)
        await i.channel.delete(reason=f"Closed by {i.user}")


# ==============================================
# TICKET COMMANDS
# ==============================================

@bot.tree.command(name="setup-ticket", description="Setup or update the ticket panel in this channel")
@app_commands.default_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    embed = await get_panel_embed(interaction.guild)
    view = TicketPanelView()

    gid = str(interaction.guild.id)
    if gid in ticket_panels:
        try:
            ch = interaction.guild.get_channel(int(ticket_panels[gid]["channel_id"]))
            if ch == interaction.channel:
                msg = await ch.fetch_message(int(ticket_panels[gid]["message_id"]))
                await msg.edit(embed=embed, view=view)
                await interaction.followup.send(embed=create_embed(description="Ticket panel updated!", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)
                return
        except Exception as e:
            print(f"Update existing panel failed: {e}")

    msg = await interaction.channel.send(embed=embed, view=view)
    ticket_panels[gid] = {
        "channel_id": str(interaction.channel.id),
        "message_id": str(msg.id)
    }
    save_data()

    await interaction.followup.send(embed=create_embed(description="Ticket panel setup complete!", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="close", description="Close the current ticket with options")
async def close(interaction: discord.Interaction):
    if "ticket-" not in interaction.channel.name.lower():
        return await interaction.response.send_message(embed=create_embed(
            title="Error ❌",
            description="This is not a ticket channel.",
            color=ERROR_COLOR,
            guild=interaction.guild
        ), ephemeral=True)

    await interaction.response.send_message(embed=create_embed(
        title="Close Ticket",
        description="Choose an action:",
        guild=interaction.guild
    ), view=CloseMenu())


@bot.tree.command(name="add", description="Add a user to the current ticket")
@app_commands.describe(user="The user to add")
async def add(interaction: discord.Interaction, user: discord.Member):
    if "ticket-" not in interaction.channel.name.lower():
        return await interaction.response.send_message(embed=create_embed(title="Error", description="This is not a ticket channel.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    try:
        await interaction.channel.set_permissions(user, view_channel=True, send_messages=True, read_messages=True)
        await interaction.response.send_message(embed=create_embed(description=f"Added {user.mention} to the ticket!", color=SUCCESS_COLOR, guild=interaction.guild))
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="remove", description="Remove a user from the current ticket")
@app_commands.describe(user="The user to remove")
async def remove(interaction: discord.Interaction, user: discord.Member):
    if "ticket-" not in interaction.channel.name.lower():
        return await interaction.response.send_message(embed=create_embed(title="Error", description="This is not a ticket channel.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    try:
        await interaction.channel.set_permissions(user, overwrite=None)
        await interaction.response.send_message(embed=create_embed(description=f"Removed {user.mention} from the ticket!", color=SUCCESS_COLOR, guild=interaction.guild))
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="rename", description="Rename the current ticket")
@app_commands.describe(new_name="New name (without 'ticket-')")
async def rename(interaction: discord.Interaction, new_name: str):
    if "ticket-" not in interaction.channel.name.lower():
        return await interaction.response.send_message(embed=create_embed(title="Error", description="This is not a ticket channel.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    new_name = f"ticket-{new_name.lower().replace(' ', '-')}"
    try:
        await interaction.channel.edit(name=new_name)
        await interaction.response.send_message(embed=create_embed(description=f"Ticket renamed to {new_name}", color=SUCCESS_COLOR, guild=interaction.guild))
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

# ==============================================
# BLACKLIST COMMANDS & AUTO-MOD
# ==============================================

@bot.tree.command(name="blacklist", description="Manage the link blacklist")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="Action to perform")
@app_commands.choices(action=[
    app_commands.Choice(name="add", value="add"),
    app_commands.Choice(name="remove", value="remove"),
    app_commands.Choice(name="list", value="list"),
    app_commands.Choice(name="setlog", value="setlog")
])
async def blacklist_cmd(interaction: discord.Interaction, action: str, pattern: str = None, channel: discord.TextChannel = None):
    global blacklisted_patterns, config

    if action == "add":
        if not pattern:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Please provide a pattern/link", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        if pattern not in blacklisted_patterns:
            blacklisted_patterns.append(pattern)
            with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(blacklisted_patterns))
            await interaction.response.send_message(embed=create_embed(description=f"Added `{pattern}` to blacklist!", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_embed(description=f"`{pattern}` already blacklisted.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    elif action == "remove":
        if not pattern:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Please provide a pattern/link", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        if pattern in blacklisted_patterns:
            blacklisted_patterns.remove(pattern)
            with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(blacklisted_patterns))
            await interaction.response.send_message(embed=create_embed(description=f"Removed `{pattern}` from blacklist!", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)
        else:
            await interaction.response.send_message(embed=create_embed(description=f"`{pattern}` not in blacklist.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    elif action == "list":
        if not blacklisted_patterns:
            return await interaction.response.send_message(embed=create_embed(description="Blacklist is empty.", color=MAIN_COLOR, guild=interaction.guild), ephemeral=True)

        embed = create_embed(title="Blacklisted Patterns", color=MAIN_COLOR, guild=interaction.guild)
        embed.description = "\n".join([f"• `{p}`" for p in blacklisted_patterns])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    elif action == "setlog":
        if not channel:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Please provide a #channel", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        config["blacklist_log_channel_id"] = channel.id
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        await interaction.response.send_message(embed=create_embed(description=f"Blacklist log channel set to {channel.mention}", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)

# ==============================================
# ANTI-NUKE
# ==============================================

@bot.event
async def on_audit_log_entry_create(entry: discord.AuditLogEntry):
    if entry.action not in [
        discord.AuditLogAction.ban,
        discord.AuditLogAction.kick,
        discord.AuditLogAction.member_role_update,
        discord.AuditLogAction.member_prune,
        discord.AuditLogAction.role_delete,
        discord.AuditLogAction.channel_delete
    ]:
        return

    if entry.user.bot or entry.user.guild_permissions.administrator:
        return

    user_id = entry.user.id
    now = datetime.utcnow().timestamp()

    nuke_actions[user_id] = [t for t in nuke_actions[user_id] if now - t < NUKE_WINDOW]
    nuke_actions[user_id].append(now)

    if len(nuke_actions[user_id]) >= NUKE_THRESHOLD:
        try:
            guild = entry.guild
            member = guild.get_member(user_id)
            if member:
                await member.timeout(until=discord.utils.utcnow() + timedelta(days=1), reason="Anti-Nuke triggered")
                for role in member.roles:
                    if role != guild.default_role:
                        await member.remove_roles(role)

            if ANTI_NUKE_LOG_CHANNEL_ID:
                log_embed = create_embed(title="ANTI-NUKE TRIGGERED 🚨", description=f"{entry.user.mention} mass action detected!", color=0xff0000, guild=guild)
                await send_log(guild, "anti_nuke", log_embed)

            print(f"ANTI-NUKE: {entry.user} timed out")

        except Exception as e:
            print(f"Anti-Nuke failed: {e}")

# ==============================================
# GIVEAWAY HELPER FUNCTIONS (muss VOR dem Command stehen!)
# ==============================================

async def check_giveaway_end(giveaway_data, message: discord.Message):
    end_time = giveaway_data["end_time"]
    while datetime.utcnow().timestamp() < end_time:
        await asyncio.sleep(30)

    await end_giveaway(message.guild, str(message.channel.id), str(message.id))


async def end_giveaway(guild: discord.Guild, channel_id: str, message_id: str):
    gid = str(guild.id)
    if gid not in giveaways or channel_id not in giveaways[gid] or message_id not in giveaways[gid][channel_id]:
        return

    giveaway = giveaways[gid][channel_id][message_id]
    if not giveaway.get("active", True):
        return

    giveaway["active"] = False
    giveaway["ended"] = datetime.utcnow().timestamp()
    participants = giveaway.get("participants", [])

    channel = guild.get_channel(int(channel_id))
    if not channel:
        save_data()
        return

    if not participants:
        await channel.send("Giveaway ended – no participants 😢")
        save_data()
        return

    winners_count = giveaway["winners"]
    winners = random.sample(participants, min(winners_count, len(participants)))
    winner_mentions = [f"<@{w}>" for w in winners]

    end_embed = create_embed(
        title="Giveaway Ended 🎉",
        description=f"**Prize:** {giveaway['prize']}\n**Winners:** {', '.join(winner_mentions)}",
        color=SUCCESS_COLOR,
        guild=guild
    )
    await channel.send(embed=end_embed)

    for winner_id in winners:
        try:
            user = await bot.fetch_user(int(winner_id))
            await user.send(f"Congratulations! You won **{giveaway['prize']}** in {guild.name}!")
        except:
            pass

    # Log
    log_embed = create_embed(
        title="Giveaway Ended",
        description=f"Prize: {giveaway['prize']}\nWinners: {', '.join(winner_mentions)}",
        color=SUCCESS_COLOR,
        guild=guild
    )
    await send_log(guild, "giveaway", log_embed)

    save_data()


async def reroll_giveaway(guild: discord.Guild, channel_id: str, message_id: str):
    gid = str(guild.id)
    giveaway = giveaways[gid][channel_id][message_id]
    participants = giveaway.get("participants", [])

    if not participants:
        return

    winners_count = giveaway["winners"]
    new_winners = random.sample(participants, min(winners_count, len(participants)))
    new_mentions = [f"<@{w}>" for w in new_winners]

    channel = guild.get_channel(int(channel_id))
    if channel:
        reroll_embed = create_embed(
            title="Giveaway Rerolled! 🎲",
            description=f"New winners: {', '.join(new_mentions)}\nPrize: {giveaway['prize']}",
            color=0xffff00,
            guild=guild
        )
        await channel.send(embed=reroll_embed)

        # Log
        log_embed = create_embed(
            title="Giveaway Rerolled",
            description=f"New winners: {', '.join(new_mentions)}\nPrize: {giveaway['prize']}",
            color=0xffff00,
            guild=guild
        )
        await send_log(guild, "giveaway", log_embed)

    save_data()

# ==============================================
# GIVEAWAY SYSTEM
# ==============================================

class GiveawayView(discord.ui.View):
    def __init__(self, message_id: str, channel_id: str):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.channel_id = channel_id

    @discord.ui.button(label="Enter Giveaway 🎉", style=discord.ButtonStyle.green, emoji="🎁")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        gid = str(interaction.guild.id)
        cid = self.channel_id
        mid = self.message_id

        if gid not in giveaways or cid not in giveaways[gid] or mid not in giveaways[gid][cid]:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)

        giveaway = giveaways[gid][cid][mid]
        participants = giveaway.get("participants", [])

        if str(interaction.user.id) in participants:
            return await interaction.response.send_message("You are already participating!", ephemeral=True)

        if giveaway.get("required_role"):
            role = interaction.guild.get_role(int(giveaway["required_role"]))
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message(f"You need the {role.mention} role to enter.", ephemeral=True)

        participants.append(str(interaction.user.id))
        giveaway["participants"] = participants
        save_data()

        # Live Update: Participants-Zahl im Embed
        try:
            msg = await interaction.channel.fetch_message(int(mid))
            embed = msg.embeds[0]
            lines = embed.description.split("\n")
            new_lines = []
            for line in lines:
                if line.startswith("**Participants:**"):
                    new_lines.append(f"**Participants:** {len(participants)}")
                else:
                    new_lines.append(line)
            embed.description = "\n".join(new_lines)
            await msg.edit(embed=embed)
        except Exception as e:
            print(f"Live update failed: {e}")

        # Persönliche Nachricht mit Leave-Button
        leave_view = discord.ui.View(timeout=None)
        leave_view.add_item(LeaveButton(mid))

        await interaction.response.send_message(
            "You have entered the giveaway! Good luck 🎉\n\n(Leave anytime with the button below)",
            view=leave_view,
            ephemeral=True
        )

        # Log Entry
        log_embed = create_embed(
            title="Giveaway Entry 🎉",
            description=f"{interaction.user.mention} entered giveaway for **{giveaway['prize']}**",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await send_log(interaction.guild, "giveaway", log_embed)


class LeaveButton(discord.ui.Button):
    def __init__(self, message_id: str):
        super().__init__(label="Leave Giveaway", style=discord.ButtonStyle.red, emoji="🚫", custom_id=f"leave_{message_id}")

    async def callback(self, interaction: discord.Interaction):
        mid = self.custom_id.split("_")[1]
        gid = str(interaction.guild.id)
        cid = str(interaction.channel.id)

        if gid not in giveaways or cid not in giveaways[gid] or mid not in giveaways[gid][cid]:
            return await interaction.response.send_message("Giveaway no longer active.", ephemeral=True)

        giveaway = giveaways[gid][cid][mid]
        participants = giveaway.get("participants", [])

        if str(interaction.user.id) not in participants:
            return await interaction.response.send_message("You are not participating.", ephemeral=True)

        participants.remove(str(interaction.user.id))
        giveaway["participants"] = participants
        save_data()

        # Haupt-Embed updaten
        try:
            msg = await interaction.channel.fetch_message(int(mid))
            embed = msg.embeds[0]
            lines = embed.description.split("\n")
            new_lines = []
            for line in lines:
                if line.startswith("**Participants:**"):
                    new_lines.append(f"**Participants:** {len(participants)}")
                else:
                    new_lines.append(line)
            embed.description = "\n".join(new_lines)
            await msg.edit(embed=embed)
        except Exception as e:
            print(f"Leave update failed: {e}")

        # Log Leave
        log_embed = create_embed(
            title="Giveaway Left",
            description=f"{interaction.user.mention} left giveaway for **{giveaway['prize']}**",
            color=0xffaa00,
            guild=interaction.guild
        )
        await send_log(interaction.guild, "giveaway", log_embed)

        await interaction.response.send_message("You have left the giveaway.", ephemeral=True)
        await interaction.message.delete()


@bot.tree.command(name="giveaway", description="Manage giveaways")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(subcommand="Subcommand", prize="Prize name", duration="Duration (e.g. 1h, 30m)", winners="Number of winners", required_role="Required role (optional)", message_id="Message ID (for end/reroll)")
@app_commands.choices(subcommand=[
    app_commands.Choice(name="create", value="create"),
    app_commands.Choice(name="end", value="end"),
    app_commands.Choice(name="reroll", value="reroll")
])
async def giveaway(interaction: discord.Interaction, subcommand: str, prize: str = None, duration: str = None, winners: int = 1, required_role: discord.Role = None, message_id: str = None):
    gid = str(interaction.guild.id)

    if subcommand == "create":
        if not prize or not duration:
            return await interaction.response.send_message("Please provide prize and duration.", ephemeral=True)

        try:
            if duration.endswith("m"):
                seconds = int(duration[:-1]) * 60
            elif duration.endswith("h"):
                seconds = int(duration[:-1]) * 3600
            elif duration.endswith("d"):
                seconds = int(duration[:-1]) * 86400
            else:
                return await interaction.response.send_message("Invalid duration. Use e.g. 1h, 30m, 2d.", ephemeral=True)
        except:
            return await interaction.response.send_message("Invalid duration format.", ephemeral=True)

        end_time = datetime.utcnow() + timedelta(seconds=seconds)

        embed = create_embed(
            title=f"🎉 Giveaway - {prize}",
            description=(
                f"**Prize:** {prize}\n"
                f"**Winners:** {winners}\n"
                f"**Ends:** <t:{int(end_time.timestamp())}:R>\n"
                f"**Required role:** {required_role.mention if required_role else 'None'}\n\n"
                f"**Participants:** 0\nClick below to enter!"
            ),
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        embed.set_footer(text=f"Hosted by {interaction.user} • ID: {interaction.id}")

        # ZUERST ohne View senden → msg existiert jetzt
        msg = await interaction.channel.send(embed=embed)

        # DANACH View mit msg.id erstellen
        view = GiveawayView(str(msg.id), str(interaction.channel.id))

        # View nachträglich hinzufügen
        await msg.edit(view=view)

        # Giveaway speichern
        if gid not in giveaways:
            giveaways[gid] = {}
        if str(interaction.channel.id) not in giveaways[gid]:
            giveaways[gid][str(interaction.channel.id)] = {}
        giveaways[gid][str(interaction.channel.id)][str(msg.id)] = {
            "prize": prize,
            "winners": winners,
            "end_time": end_time.timestamp(),
            "host": str(interaction.user.id),
            "participants": [],
            "required_role": str(required_role.id) if required_role else None,
            "active": True,
            "message_id": str(msg.id)
        }
        save_data()

        # Log
        log_embed = create_embed(
            title="Giveaway Created 🎉",
            description=f"By {interaction.user.mention}\nPrize: {prize}\nWinners: {winners}\nEnds: <t:{int(end_time.timestamp())}:R>",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        log_embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
        await send_log(interaction.guild, "giveaway", log_embed)

        await interaction.response.send_message(f"Giveaway created! Ends <t:{int(end_time.timestamp())}:R>", ephemeral=True)

        bot.loop.create_task(check_giveaway_end(giveaways[gid][str(interaction.channel.id)][str(msg.id)], msg))

    elif subcommand == "end":
        if not message_id:
            return await interaction.response.send_message("Please provide message ID.", ephemeral=True)

        found = False
        for cid, msgs in giveaways.get(gid, {}).items():
            if message_id in msgs:
                giveaway = msgs[message_id]
                found = True
                break

        if not found:
            return await interaction.response.send_message("Giveaway not found.", ephemeral=True)

        await end_giveaway(interaction.guild, cid, message_id)
        await interaction.response.send_message("Giveaway ended!", ephemeral=True)

    elif subcommand == "reroll":
        if not message_id:
            return await interaction.response.send_message("Please provide message ID.", ephemeral=True)

        found = False
        for cid, msgs in giveaways.get(gid, {}).items():
            if message_id in msgs:
                giveaway = msgs[message_id]
                if giveaway.get("ended"):
                    found = True
                    break

        if not found:
            return await interaction.response.send_message("Giveaway not found or still active.", ephemeral=True)

        await reroll_giveaway(interaction.guild, cid, message_id)
        await interaction.response.send_message("Rerolled!", ephemeral=True)

@bot.tree.command(name="log-setup", description="Setup all log channels automatically")
@app_commands.default_permissions(administrator=True)
async def log_setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    guild = interaction.guild

    try:
        # Kategorie erstellen, wenn nicht vorhanden
        log_category = discord.utils.get(guild.categories, name="Logs")
        if not log_category:
            log_category = await guild.create_category("Logs", reason="Log Setup by LiaMae")
            await log_category.edit(position=0)  # ganz oben

        # Channels und ihre Keys
        channels_to_create = {
            "transcript-logs": {
                "topic": "Ticket Transcripts 📜",
                "id_key": "transcript_channel_id"
            },
            "blacklist-logs": {
                "topic": "Blacklist Violations 🚫",
                "id_key": "blacklist_log_channel_id"
            },
            "mod-logs": {
                "topic": "Moderation Actions 🔨",
                "id_key": "mod_log_channel_id"
            },
            "anti-nuke-logs": {
                "topic": "Anti-Nuke Alerts 🚨",
                "id_key": "anti_nuke_log_channel_id"
            },
            "announce-logs": {
                "topic": "Announcements 📢",
                "id_key": "announce_log_channel_id"
            }
        }

        created_channels = []

        for name, data in channels_to_create.items():
            channel = discord.utils.get(guild.text_channels, name=name)
            if not channel:
                channel = await guild.create_text_channel(
                    name=name,
                    category=log_category,
                    topic=data["topic"],
                    reason="Log Setup by LiaMae"
                )

                # Permissions setzen
                await channel.set_permissions(guild.default_role, send_messages=False, view_channel=True)
                await channel.set_permissions(guild.me, send_messages=True, view_channel=True, read_message_history=True)

                if SUPPORT_ROLE_ID:
                    support_role = guild.get_role(SUPPORT_ROLE_ID)
                    if support_role:
                        await channel.set_permissions(support_role, send_messages=True, view_channel=True, read_message_history=True)

            # ID in config speichern
            config[data["id_key"]] = channel.id
            created_channels.append(f"• {channel.mention} → {data['topic']}")

        # Config speichern
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        # Bestätigungs-Embed
        embed = create_embed(
            title="Log Setup Complete! ✅",
            description="All log channels created and configured.",
            color=SUCCESS_COLOR,
            guild=guild
        )
        embed.add_field(name="Category", value=log_category.mention, inline=False)
        embed.add_field(name="Channels", value="\n".join(created_channels), inline=False)
        embed.add_field(name="Next Step", value="Test with /warn, /announce, blacklist link, etc.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(embed=create_embed(
            title="Error During Setup",
            description=str(e),
            color=ERROR_COLOR,
            guild=guild
        ), ephemeral=True)


# ==============================================
# TICKET CATEGORY MANAGEMENT
# ==============================================

@bot.tree.command(name="ticketcategory", description="Manage ticket categories")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="What to do?")
@app_commands.choices(action=[
    app_commands.Choice(name="add", value="add"),
    app_commands.Choice(name="remove", value="remove"),
    app_commands.Choice(name="edit", value="edit"),
    app_commands.Choice(name="list", value="list")
])
async def ticketcategory(
    interaction: discord.Interaction,
    action: str,
    value: str = None,
    label: str = None,
    description: str = None,
    emoji: str = None,
    opening_message: str = None
):
    global config, TICKET_TYPES

    ticket_panel = config.setdefault("TICKET_PANEL", {})
    TICKET_TYPES = ticket_panel.setdefault("ticket_types", [])

    if action == "add":
        if not all([value, label]):
            return await interaction.response.send_message(embed=create_embed(
                title="Error ❌",
                description="You need at least value and label.",
                color=ERROR_COLOR
            ), ephemeral=True)

        if any(t["value"] == value for t in TICKET_TYPES):
            return await interaction.response.send_message(embed=create_embed(
                title="Error ❌",
                description=f"Value {value} already exists.",
                color=ERROR_COLOR
            ), ephemeral=True)

        new_category = {
            "label": label,
            "value": value,
            "description": description or f"{label} support",
            "emoji": emoji or "❓",
            "opening_embed_description": opening_message or "Hello {user}!\n\n**Please describe your issue in detail:**\n• What happened?\n• Any IDs / usernames?\n• Screenshots if possible\n\nSupport will be with you soon! ⏳"
        }

        TICKET_TYPES.append(new_category)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        await interaction.response.send_message(embed=create_embed(
            title="Category Added ✅",
            description=f"{label} ({value}) added.",
            color=SUCCESS_COLOR
        ), ephemeral=True)

        await update_all_panels()

    elif action == "remove":
        if not value:
            return await interaction.response.send_message(embed=create_embed(
                title="Error ❌",
                description="Please provide the value to remove.",
                color=ERROR_COLOR
            ), ephemeral=True)

        old_length = len(TICKET_TYPES)
        TICKET_TYPES[:] = [t for t in TICKET_TYPES if t["value"] != value]

        if len(TICKET_TYPES) == old_length:
            return await interaction.response.send_message(embed=create_embed(
                title="Error ❌",
                description=f"No category with value {value} found.",
                color=ERROR_COLOR
            ), ephemeral=True)

        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        await interaction.response.send_message(embed=create_embed(
            title="Category Removed ✅",
            description=f"Category {value} removed.",
            color=SUCCESS_COLOR
        ), ephemeral=True)

        await update_all_panels()

    elif action == "edit":
        if not value:
            return await interaction.response.send_message(embed=create_embed(
                title="Error ❌",
                description="Please provide the value to edit.",
                color=ERROR_COLOR
            ), ephemeral=True)

        category = next((t for t in TICKET_TYPES if t["value"] == value), None)
        if not category:
            return await interaction.response.send_message(embed=create_embed(
                title="Error ❌",
                description=f"No category with value {value} found.",
                color=ERROR_COLOR
            ), ephemeral=True)

        updated = False
        if label is not None:
            category["label"] = label
            updated = True
        if description is not None:
            category["description"] = description
            updated = True
        if emoji is not None:
            category["emoji"] = emoji
            updated = True
        if opening_message is not None:
            category["opening_embed_description"] = opening_message
            updated = True

        if not updated:
            return await interaction.response.send_message(embed=create_embed(
                title="Nothing Changed ⚠️",
                description="Provide at least one field to edit.",
                color=ERROR_COLOR
            ), ephemeral=True)

        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        await interaction.response.send_message(embed=create_embed(
            title="Category Updated ✅",
            description=f"Category {value} updated.",
            color=SUCCESS_COLOR
        ), ephemeral=True)

        await update_all_panels()

    elif action == "list":
        if not TICKET_TYPES:
            return await interaction.response.send_message(embed=create_embed(
                title="No Categories",
                description="There are no ticket categories yet.",
                color=MAIN_COLOR
            ), ephemeral=True)

        embed = create_embed(title="Current Ticket Categories", color=MAIN_COLOR)
        for t in TICKET_TYPES:
            embed.add_field(
                name=f"{t.get('emoji', '❓')} {t['label']} ({t['value']})",
                value=f"**Description:** {t.get('description', '—')}\n**Opening Message:** {t.get('opening_embed_description', 'Default')[:100]}...",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==============================================
# VOUCH SYSTEM
# ==============================================

@bot.tree.command(name="vouch", description="Leave a vouch for a user")
@app_commands.describe(user="User", stars="1-5 stars", review="Your review")
async def vouch(interaction: discord.Interaction, user: discord.User, stars: int, review: str):
    if stars < 1 or stars > 5:
        return await interaction.response.send_message(embed=create_embed(title="Error", description="Stars must be 1-5.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    gid = str(interaction.guild.id)
    uid = str(user.id)

    if gid not in vouches:
        vouches[gid] = {}
    if uid not in vouches[gid]:
        vouches[gid][uid] = []

    vouches[gid][uid].append({
        "from": interaction.user.id,
        "stars": stars,
        "review": review,
        "time": datetime.utcnow().isoformat()
    })

    save_data()

    embed = create_embed(title="New Vouch Received! ⭐", guild=interaction.guild)
    embed.add_field(name="Review:", value=f"**{'★' * stars}{'☆' * (5 - stars)}**\n{review}", inline=False)
    embed.add_field(name="Vouched by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Vouched at", value=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), inline=True)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="vouches", description="Show vouches for a user")
@app_commands.describe(user="User (optional)")
async def vouches(interaction: discord.Interaction, user: discord.User = None):
    target = user or interaction.user
    gid = str(interaction.guild.id)
    uid = str(target.id)

    if gid not in vouches or uid not in vouches[gid]:
        return await interaction.response.send_message(embed=create_embed(
            description=f"No vouches found for {target.mention} yet",
            guild=interaction.guild
        ))

    entries = vouches[gid][uid]
    avg = sum(e["stars"] for e in entries) / len(entries)

    embed_obj = create_embed(title=f"Vouches • {target.display_name}", description=f"Average: **{avg:.1f}/5**  •  Total: **{len(entries)}**", guild=interaction.guild)

    for e in entries[-10:]:
        from_user = interaction.guild.get_member(int(e["from"]))
        name = from_user.display_name if from_user else f"ID {e['from']}"
        embed_obj.add_field(name=f"{e['stars']}⭐ from {name}", value=e["review"][:150] or "—", inline=False)

    await interaction.response.send_message(embed=embed_obj)


@bot.tree.command(name="restore", description="Restore all vouches from vouches.json into this channel")
@app_commands.default_permissions(administrator=True)
async def restore(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    if not os.path.exists(VOUCHES_FILE):
        return await interaction.followup.send(embed=create_embed(title="Error", description="vouches.json not found", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    try:
        with open(VOUCHES_FILE, "r") as f:
            data = json.load(f)
    except Exception as e:
        return await interaction.followup.send(embed=create_embed(title="Error", description=f"Failed to read file:\n{str(e)}", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    restored = 0

    for guild_id_str, users in data.items():
        for user_id_str, entries in users.items():
            for entry in entries:
                restored += 1

                stars = entry.get("stars", 5)
                stars_display = "★" * stars + "☆" * (5 - stars)
                review = entry.get("review", entry.get("comment", "No review provided"))
                time_str = entry.get("time", "Unknown time")

                e = create_embed(title="New Vouch Received! ⭐", guild=interaction.guild)
                e.add_field(name="Review:", value=f"**{stars_display}**\n{review}", inline=False)
                e.add_field(name="Vouched by", value=f"<@{entry['from']}>", inline=True)
                e.add_field(name="Vouched at", value=time_str, inline=True)

                await interaction.channel.send(embed=e)
                await asyncio.sleep(1.1)

    await interaction.followup.send(embed=create_embed(description=f"**{restored}** vouches restored and sent!", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)


# ==============================================
# MODERATION COMMANDS
# ==============================================

@bot.tree.command(name="warn", description="Warn a user")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(user="The user to warn", reason="Reason for the warning")
async def warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    gid = str(interaction.guild.id)
    uid = str(user.id)

    if gid not in warnings:
        warnings[gid] = {}
    if uid not in warnings[gid]:
        warnings[gid][uid] = []

    warnings[gid][uid].append({
        "reason": reason,
        "mod": interaction.user.display_name,
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    })

    save_data()

    try:
        warn_embed = create_embed(
            title="Warning Issued ⚠️",
            description=f"You received a warning in **{interaction.guild.name}**.\n**Reason:** {reason}\n**Moderator:** {interaction.user.mention}",
            color=0xffaa00,
            guild=interaction.guild
        )
        await user.send(embed=warn_embed)
    except:
        pass

    log_embed = create_embed(
        title="User Warned ⚠️",
        description=f"{user.mention} was warned by {interaction.user.mention}.",
        color=0xffaa00,
        guild=interaction.guild
    )
    log_embed.add_field(name="Reason", value=reason, inline=False)
    log_embed.add_field(name="Total Warnings", value=len(warnings[gid][uid]), inline=True)

    await interaction.response.send_message(embed=log_embed)
    await send_log(interaction.guild, "mod", log_embed)


@bot.tree.command(name="warnings", description="Show warnings of a user")
@app_commands.describe(user="The user (optional, defaults to yourself)")
async def warnings_cmd(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    gid = str(interaction.guild.id)
    uid = str(target.id)

    if gid not in warnings or uid not in warnings[gid] or not warnings[gid][uid]:
        return await interaction.response.send_message(embed=create_embed(
            title=f"Warnings • {target.display_name}",
            description="This user has **no warnings**.",
            color=MAIN_COLOR,
            guild=interaction.guild
        ), ephemeral=True)

    embed = create_embed(title=f"Warnings • {target.display_name} ⚠️", color=0xffaa00, guild=interaction.guild)
    for i, w in enumerate(warnings[gid][uid], 1):
        embed.add_field(
            name=f"Warning #{i}",
            value=f"**Reason:** {w['reason']}\n**By:** {w['mod']}\n**At:** {w['time']}",
            inline=False
        )
    embed.set_footer(text=f"Total: {len(warnings[gid][uid])} warnings")

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="Clear all warnings of a user")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(user="The user to clear warnings for")
async def clearwarnings(interaction: discord.Interaction, user: discord.Member):
    gid = str(interaction.guild.id)
    uid = str(user.id)

    if gid in warnings and uid in warnings[gid]:
        del warnings[gid][uid]
        if not warnings[gid]:
            del warnings[gid]

        with open(WARNINGS_FILE, "w") as f:
            json.dump(warnings, f, indent=2)

        await interaction.response.send_message(embed=create_embed(
            title="Warnings Cleared ✅",
            description=f"All warnings for {user.mention} have been cleared.",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        ))
    else:
        await interaction.response.send_message(embed=create_embed(
            title="No Warnings",
            description=f"{user.mention} has no warnings to clear.",
            color=MAIN_COLOR,
            guild=interaction.guild
        ), ephemeral=True)


@bot.tree.command(name="mute", description="Mute a user for a specific time")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(user="User to mute", duration="Duration (e.g. 30m, 2h, 1d)", reason="Reason (optional)")
async def mute(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason provided"):
    try:
        if duration.endswith("m"):
            delta = timedelta(minutes=int(duration[:-1]))
        elif duration.endswith("h"):
            delta = timedelta(hours=int(duration[:-1]))
        elif duration.endswith("d"):
            delta = timedelta(days=int(duration[:-1]))
        else:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Invalid duration! Use e.g. 30m, 2h, 1d", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        await user.timeout(until=discord.utils.utcnow() + delta, reason=reason)

        log_embed = create_embed(
            title="User Muted ⏳",
            description=f"{user.mention} muted for **{duration}** by {interaction.user.mention}.\nReason: {reason}",
            color=0xffaa00,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)

    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="unmute", description="Unmute a user")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(user="User to unmute")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    try:
        await user.timeout(until=None)

        log_embed = create_embed(
            title="User Unmuted ✅",
            description=f"{user.mention} has been unmuted by {interaction.user.mention}.",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)

    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="slowmode", description="Set slowmode in current channel")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(seconds="Seconds (0 to disable)", reason="Reason (optional)")
async def slowmode(interaction: discord.Interaction, seconds: int, reason: str = "No reason provided"):
    if seconds < 0 or seconds > 21600:
        return await interaction.response.send_message(embed=create_embed(title="Error", description="Seconds must be 0–21600", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    try:
        await interaction.channel.edit(slowmode_delay=seconds)
        status = "disabled" if seconds == 0 else f"set to **{seconds}s**"
        log_embed = create_embed(
            title="Slowmode Updated ⏱️",
            description=f"Slowmode in {interaction.channel.mention} {status}.\nReason: {reason}",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="lock", description="Lock current channel")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(reason="Reason (optional)")
async def lock(interaction: discord.Interaction, reason: str = "No reason provided"):
    try:
        overwrites = interaction.channel.overwrites
        overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(send_messages=False)
        await interaction.channel.edit(overwrites=overwrites)

        log_embed = create_embed(
            title="Channel Locked 🔐",
            description=f"{interaction.channel.mention} is now locked.\nReason: {reason}",
            color=0xff5555,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="unlock", description="Unlock current channel")
@app_commands.default_permissions(manage_channels=True)
@app_commands.describe(reason="Reason (optional)")
async def unlock(interaction: discord.Interaction, reason: str = "No reason provided"):
    try:
        overwrites = interaction.channel.overwrites
        overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(send_messages=None)
        await interaction.channel.edit(overwrites=overwrites)

        log_embed = create_embed(
            title="Channel Unlocked 🔓",
            description=f"{interaction.channel.mention} is now unlocked.\nReason: {reason}",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="clear", description="Clear messages in current channel")
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(amount="Number of messages to delete (1–100)")
async def clear(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        return await interaction.response.send_message(embed=create_embed(title="Error", description="Amount must be 1–100", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

    try:
        deleted = await interaction.channel.purge(limit=amount + 1)
        log_embed = create_embed(
            title="Messages Cleared 🧹",
            description=f"Deleted **{len(deleted)-1}** messages.",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed, delete_after=10)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="nick", description="Change or reset a user's nickname")
@app_commands.default_permissions(manage_nicknames=True)
@app_commands.describe(user="The user", nickname="New nickname (empty to reset)")
async def nick(interaction: discord.Interaction, user: discord.Member, nickname: str = None):
    try:
        if nickname:
            await user.edit(nick=nickname)
            log_embed = create_embed(
                title="Nickname Changed ✏️",
                description=f"{user.mention}'s nickname set to **{nickname}** by {interaction.user.mention}",
                color=SUCCESS_COLOR,
                guild=interaction.guild
            )
        else:
            await user.edit(nick=None)
            log_embed = create_embed(
                title="Nickname Reset 🔄",
                description=f"{user.mention}'s nickname reset by {interaction.user.mention}",
                color=SUCCESS_COLOR,
                guild=interaction.guild
            )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="announce", description="Send an announcement with @everyone ping")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(message="The announcement message")
async def announce(interaction: discord.Interaction, message: str):
    embed = create_embed(
        title="📢 Server Announcement",
        description=message,
        color=0x00aaff,
        guild=interaction.guild
    )

    await interaction.channel.send(
        content="@everyone",
        embed=embed
    )

    log_embed = create_embed(
        title="Announcement Sent 📢",
        description=f"By {interaction.user.mention}:\n{message}",
        color=0x00aaff,
        guild=interaction.guild
    )
    await interaction.response.send_message(embed=create_embed(
        title="Announcement Sent! 🚀",
        description="Your message has been broadcasted with @everyone ping.",
        color=SUCCESS_COLOR,
        guild=interaction.guild
    ), ephemeral=True)
    await send_log(interaction.guild, "announce", log_embed)


@bot.tree.command(name="user", description="Show info about a user")
@app_commands.describe(user="The user (optional, defaults to you)")
async def user_info(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    gid = str(interaction.guild.id)
    uid = str(target.id)

    warn_count = len(warnings.get(gid, {}).get(uid, []))

    embed = create_embed(title=f"User Info • {target.display_name}", color=MAIN_COLOR, guild=interaction.guild)
    embed.set_thumbnail(url=target.avatar.url if target.avatar else None)

    embed.add_field(name="ID", value=target.id, inline=True)
    embed.add_field(name="Joined Server", value=discord.utils.format_dt(target.joined_at, "R"), inline=True)
    embed.add_field(name="Account Created", value=discord.utils.format_dt(target.created_at, "R"), inline=True)
    embed.add_field(name="Top Role", value=target.top_role.mention if target.top_role else "None", inline=True)
    embed.add_field(name="Warnings", value=f"**{warn_count}** ⚠️", inline=True)

    roles = ", ".join([r.mention for r in target.roles if r != interaction.guild.default_role]) or "None"
    embed.add_field(name="Roles", value=roles, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="roleadd", description="Add a role to a user")
@app_commands.default_permissions(manage_roles=True)
@app_commands.describe(user="The user", role="The role")
async def roleadd(interaction: discord.Interaction, user: discord.Member, role: discord.Role):
    try:
        await user.add_roles(role)
        log_embed = create_embed(
            title="Role Added",
            description=f"{role.mention} added to {user.mention} by {interaction.user.mention}",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="roleremove", description="Remove a role from a user")
@app_commands.default_permissions(manage_roles=True)
@app_commands.describe(user="The user", role="The role")
async def roleremove(interaction: discord.Interaction, user: discord.Member, role: discord.Role):
    try:
        await user.remove_roles(role)
        log_embed = create_embed(
            title="Role Removed",
            description=f"{role.mention} removed from {user.mention} by {interaction.user.mention}",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="ban", description="Ban a user")
@app_commands.default_permissions(ban_members=True)
@app_commands.describe(user="The user to ban", reason="Reason (optional)")
async def ban(interaction: discord.Interaction, user: discord.User, reason: str = "No reason provided"):
    try:
        await interaction.guild.ban(user, reason=reason)
        log_embed = create_embed(
            title="User Banned 🔨",
            description=f"{user.mention} banned by {interaction.user.mention}.\nReason: {reason}",
            color=0xff0000,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="unban", description="Unban a user")
@app_commands.default_permissions(ban_members=True)
@app_commands.describe(user="The user to unban")
async def unban(interaction: discord.Interaction, user: discord.User):
    try:
        await interaction.guild.unban(user)
        log_embed = create_embed(
            title="User Unbanned 🔓",
            description=f"{user.mention} unbanned by {interaction.user.mention}.",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="timeout", description="Timeout a user")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(user="The user", duration="Duration (e.g. 30m, 1h, 1d)")
async def timeout(interaction: discord.Interaction, user: discord.Member, duration: str):
    try:
        if duration.endswith("m"):
            delta = timedelta(minutes=int(duration[:-1]))
        elif duration.endswith("h"):
            delta = timedelta(hours=int(duration[:-1]))
        elif duration.endswith("d"):
            delta = timedelta(days=int(duration[:-1]))
        else:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Invalid duration.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        await user.timeout(until=discord.utils.utcnow() + delta)
        log_embed = create_embed(
            title="User Timed Out ⏳",
            description=f"{user.mention} timed out for {duration} by {interaction.user.mention}.",
            color=0xffaa00,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="untimeout", description="Remove timeout from a user")
@app_commands.default_permissions(moderate_members=True)
@app_commands.describe(user="The user")
async def untimeout(interaction: discord.Interaction, user: discord.Member):
    try:
        await user.timeout(until=None)
        log_embed = create_embed(
            title="Timeout Removed ⏳",
            description=f"Timeout removed from {user.mention} by {interaction.user.mention}.",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=log_embed)
        await send_log(interaction.guild, "mod", log_embed)
    except Exception as e:
        await interaction.response.send_message(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

# ==============================================
# WELCOMER
# ==============================================

@bot.event
async def on_member_join(member: discord.Member):
    if not WELCOME_CHANNEL_ID:
        print("[WELCOME] No welcome_channel_id set in config")
        return

    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        print(f"[WELCOME] Channel {WELCOME_CHANNEL_ID} not found")
        return

    try:
        # 1. Normale Nachricht mit Ping (das ist der @user)
        await channel.send(f"{member.mention}")

        # 2. Danach die Embed senden
        msg = WELCOME_MESSAGE.format(user=member.mention)

        embed = create_embed(
            title="Developed by LiaMae",
            description=msg,
            color=MAIN_COLOR,
            guild=member.guild
        )

        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        if member.guild.banner:
            embed.set_image(url=member.guild.banner.url)

        embed.set_footer(text=FOOTER_TEXT)

        await channel.send(embed=embed)
        print(f"[WELCOME] Sent ping + embed to {member} in {channel.name}")

    except discord.Forbidden:
        print("[WELCOME] Missing permissions in channel")
    except Exception as e:
        print(f"[WELCOME ERROR] {e}")


@bot.tree.command(name="welcomer", description="Configure welcome messages")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(action="What do you want to do?")
@app_commands.choices(action=[
    app_commands.Choice(name="setchannel", value="setchannel"),
    app_commands.Choice(name="setmessage", value="setmessage"),
    app_commands.Choice(name="test", value="test")
])
async def welcomer(interaction: discord.Interaction, action: str, channel: discord.TextChannel = None, message: str = None):
    global config

    if action == "setchannel":
        if not channel:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Please provide a #channel", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        config["welcome_channel_id"] = channel.id
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        await interaction.response.send_message(embed=create_embed(description=f"Welcome channel set to {channel.mention}", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)

    elif action == "setmessage":
        if not message:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Please provide a message text", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        config["welcome_message"] = message
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        preview = message.format(user=interaction.user.mention)
        await interaction.response.send_message(embed=create_embed(title="Welcome Message Updated", description=f"Preview:\n{preview}", color=SUCCESS_COLOR, guild=interaction.guild), ephemeral=True)

    elif action == "test":
        if not config.get("welcome_channel_id"):
            return await interaction.response.send_message(embed=create_embed(title="Error", description="No welcome channel set. Use /welcomer setchannel first.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        ch = bot.get_channel(config["welcome_channel_id"])
        if not ch:
            return await interaction.response.send_message(embed=create_embed(title="Error", description="Welcome channel not found.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        # Exakt wie beim echten Join
        # 1. Ping-Nachricht
        await ch.send(f"{interaction.user.mention}")

        # 2. Embed
        msg = config.get("welcome_message", "Welcome {user} to the server! 🎉")
        formatted = msg.format(user=interaction.user.mention)

        embed = create_embed(
            title="Welcome Test! 💜",
            description=formatted,
            color=MAIN_COLOR,
            guild=interaction.guild
        )

        if interaction.user.avatar:
            embed.set_thumbnail(url=interaction.user.avatar.url)

        if interaction.guild.banner:
            embed.set_image(url=interaction.guild.banner.url)

        await ch.send(embed=embed)

        await interaction.response.send_message(embed=create_embed(
            description="Test welcome sent exactly like real join (ping + embed)!",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        ), ephemeral=True)


# ==============================================
# INVITES & LEADERBOARD
# ==============================================

@bot.tree.command(name="invites", description="Show your active invites and uses")
async def invites(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        invites = await interaction.guild.invites()
        my_invites = [inv for inv in invites if inv.inviter == interaction.user]

        if not my_invites:
            return await interaction.followup.send(embed=create_embed(description="You have no active invites.", color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)

        embed = create_embed(title=f"Your Invites • {interaction.user.display_name}", color=MAIN_COLOR, guild=interaction.guild)
        total_uses = 0

        for inv in my_invites[:10]:
            embed.add_field(
                name=f"https://discord.gg/{inv.code}",
                value=f"Uses: **{inv.uses}** • Max Age: {inv.max_age // 86400 if inv.max_age else 'Unlimited'} days",
                inline=False
            )
            total_uses += inv.uses

        embed.add_field(name="Total Uses", value=str(total_uses), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


@bot.tree.command(name="leaderboard", description="Top inviters leaderboard")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        invites = await interaction.guild.invites()
        inviter_uses = defaultdict(int)

        for inv in invites:
            if inv.inviter:
                inviter_uses[inv.inviter.id] += inv.uses

        sorted_users = sorted(inviter_uses.items(), key=lambda x: x[1], reverse=True)[:10]

        embed = create_embed(title="🏆 Invite Leaderboard", color=MAIN_COLOR, guild=interaction.guild)
        for i, (user_id, uses) in enumerate(sorted_users, 1):
            user = await bot.fetch_user(user_id)
            embed.add_field(
                name=f"{i}. {user.display_name}",
                value=f"**{uses}** invites",
                inline=False
            )

        if not sorted_users:
            embed.description = "No invite data available yet."

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        await interaction.followup.send(embed=create_embed(title="Error", description=str(e), color=ERROR_COLOR, guild=interaction.guild), ephemeral=True)


# ==============================================
# HELP COMMAND
# ==============================================

@bot.tree.command(name="help", description="Show all commands")
async def help_cmd(interaction: discord.Interaction):
    e = create_embed(title="LiaMae • Command Overview 🌟", guild=interaction.guild)

    e.add_field(
        name="🎟️ Tickets",
        value="`/setup-ticket` `/close` `/add` `/remove` `/rename` `/ticketcategory` `/feedback` `/reminder`",
        inline=False
    )

    e.add_field(
        name="⭐ Vouch",
        value="`/vouch` `/vouches` `/restore`",
        inline=False
    )

    e.add_field(
        name="🔨 Moderation",
        value="`/warn` `/warnings` `/clearwarnings` `/mute` `/unmute` `/slowmode` `/lock` `/unlock` `/clear` `/nick` `/announce` `/user` `/purge` `/roleadd` `/roleremove` `/timeout` `/untimeout` `/ban` `/unban`",
        inline=False
    )

    e.add_field(
        name="📢 Utility",
        value="`/welcomer` `/blacklist` `/invites` `/leaderboard` `/log-setup` `/giveaway` `/stats` `/help`",
        inline=False
    )

    await interaction.response.send_message(embed=e, ephemeral=False)


# ==============================================
# FEEDBACK SYSTEM + 24H AUTO TASK (using vouches.json)
# ==============================================

async def auto_feedback_task(channel_id: int):
    await asyncio.sleep(24 * 3600)  # 24 Stunden

    if channel_id not in open_tickets:
        return

    data = open_tickets[channel_id]
    
    # Wenn Feedback schon gegeben wurde → nichts tun
    if data.get("feedback_given"):
        open_tickets.pop(channel_id, None)
        return

    guild = bot.get_guild(data["guild_id"])
    if not guild:
        open_tickets.pop(channel_id, None)
        return

    # Auto Vouch in vouches.json speichern
    gid = str(guild.id)
    uid = str(data["user_id"])

    if gid not in vouches:
        vouches[gid] = {}
    if uid not in vouches[gid]:
        vouches[gid][uid] = []

    vouches[gid][uid].append({
        "from": bot.user.id,           # Bot als "Voucher"
        "stars": 5,                    # Mittelwert bei Auto
        "review": "Automatic vouch after 24h without feedback",
        "time": datetime.utcnow().isoformat(),
        "type": "auto_feedback"
    })

    save_data()

    # Optional: Auto-Vouch auch im Channel posten
    vouch_id = config.get(str(guild.id), {}).get("vouch_channel")
    if vouch_id:
        vouch_ch = guild.get_channel(vouch_id)
        if vouch_ch:
            embed = create_embed(title="🌟 Automatic Vouch (24h)")
            embed.add_field(name="Rating", value="3/5 (auto)", inline=True)
            embed.add_field(name="User", value=f"<@{data['user_id']}>", inline=True)
            embed.add_field(name="Reason", value="No feedback received within 24 hours", inline=False)
            await vouch_ch.send(embed=embed)

    # Ticket löschen
    ch = guild.get_channel(channel_id)
    if ch:
        try:
            await ch.delete(reason="Auto-closed after 24h without feedback")
        except:
            pass

    open_tickets.pop(channel_id, None)


class FeedbackView(discord.ui.View):
    def __init__(self, ticket_channel_id: int):
        super().__init__(timeout=None)
        self.ticket_channel_id = ticket_channel_id

    @discord.ui.select(
        placeholder="How satisfied are you with the support?",
        options=[
            discord.SelectOption(label="Very Bad", value="1", emoji="😡"),
            discord.SelectOption(label="Bad", value="2", emoji="🙁"),
            discord.SelectOption(label="Okay", value="3", emoji="😐"),
            discord.SelectOption(label="Good", value="4", emoji="🙂"),
            discord.SelectOption(label="Excellent", value="5", emoji="😍"),
        ]
    )
    async def feedback_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        rating = int(select.values[0])
        stars = "⭐" * rating

        gid = str(interaction.guild.id)
        uid = str(interaction.user.id)

        if gid not in vouches:
            vouches[gid] = {}
        if uid not in vouches[gid]:
            vouches[gid][uid] = []

        # ← Genau gleiches Format wie im auto_feedback_task
        vouches[gid][uid].append({
            "from": interaction.user.id,
            "stars": rating,
            "review": f"Ticket Feedback: {stars}",
            "time": datetime.utcnow().isoformat(),
            "type": "ticket_feedback"
        })

        save_data()

        # Markiere Feedback als gegeben (für Auto-Task)
        if interaction.channel.id in open_tickets:
            open_tickets[interaction.channel.id]["feedback_given"] = True

        # Public Nachricht im Ticket
        public_embed = create_embed(
            title="📊 New Feedback Received",
            description=f"{interaction.user.mention} rated this ticket **{stars}** ({rating}/5)",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.channel.send(embed=public_embed)

        # Danke Nachricht
        thank_embed = create_embed(
            title="✅ Thank You!",
            description=f"Your feedback **{stars}** has been saved.",
            color=SUCCESS_COLOR,
            guild=interaction.guild
        )
        await interaction.response.send_message(embed=thank_embed, ephemeral=True)


@bot.tree.command(name="feedback", description="Rate your support experience (only in tickets)")
async def feedback(i: discord.Interaction):
    if "ticket-" not in i.channel.name.lower():
        return await i.response.send_message(
            embed=create_embed(title="❌ Error", 
                             description="This command can only be used inside tickets.", 
                             color=ERROR_COLOR, 
                             guild=i.guild),
            ephemeral=True
        )

    embed = create_embed(title="📝 Feedback", description="How was your support experience?")
    await i.response.send_message(embed=embed, view=FeedbackView(i.channel.id))


# ==============================================
# REMINDER COMMAND + IMPROVED TRANSCRIPT SYSTEM
# ==============================================

@bot.tree.command(name="reminder", description="Send reminder to ticket creator and activate 24h auto-close")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(message="Custom message (optional)")
async def reminder(i: discord.Interaction, message: str = "Your ticket is still open. Please respond soon or it will be automatically closed."):
    if "ticket-" not in i.channel.name.lower():
        return await i.response.send_message(
            embed=create_embed(title="❌ Error", 
                             description="This command can only be used in ticket channels.", 
                             color=ERROR_COLOR, 
                             guild=i.guild),
            ephemeral=True
        )

    # Ticket Creator finden
    ticket_creator = None
    async for msg in i.channel.history(limit=50, oldest_first=True):
        if msg.author != i.guild.me and not msg.author.bot:
            ticket_creator = msg.author
            break

    if not ticket_creator:
        return await i.response.send_message("Could not find ticket creator.", ephemeral=True)

    embed = create_embed(title="🕒 Ticket Reminder", description=message, color=0xffaa00, guild=i.guild)
    embed.add_field(name="Ticket", value=i.channel.mention, inline=False)

    await i.response.defer(ephemeral=True)

    try:
        await ticket_creator.send(embed=embed)
        await i.channel.send(embed=create_embed(
            title="✅ Reminder Sent", 
            description=f"{ticket_creator.mention} has been reminded via DM.", 
            color=0xffaa00, 
            guild=i.guild
        ))
        await i.followup.send("Reminder sent successfully!", ephemeral=True)
    except:
        await i.followup.send("❌ Could not send DM (user has DMs disabled).", ephemeral=True)

# ==============================================
# CLOSE REQUEST COMMAND
# ==============================================

class CloseRequestView(discord.ui.View):
    def __init__(self, ticket_channel_id: int, owner_id: int):
        super().__init__(timeout=None)
        self.ticket_channel_id = ticket_channel_id
        self.owner_id = owner_id

    @discord.ui.button(label="Accept & Close Ticket", style=discord.ButtonStyle.red, emoji="🔒")
    async def accept_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("Only the ticket owner can accept this request.", ephemeral=True)

        await interaction.response.defer()

        channel = interaction.guild.get_channel(self.ticket_channel_id)
        if not channel:
            return await interaction.followup.send("Ticket channel not found.", ephemeral=True)

        transcript_text = await create_transcript(channel)

        # Log Channel
        if TRANSCRIPT_CHANNEL_ID:
            log_channel = interaction.guild.get_channel(TRANSCRIPT_CHANNEL_ID)
            if log_channel:
                file = discord.File(fp=transcript_text.encode('utf-8'), filename=f"transcript-{channel.name}.txt")
                await log_channel.send(f"**Transcript** • `{channel.name}` (closed via /close-request)", file=file)

        # DM an Owner
        try:
            file = discord.File(fp=transcript_text.encode('utf-8'), filename=f"transcript-{channel.name}.txt")
            await interaction.user.send(f"**Your ticket `{channel.name}` has been closed.**\nHere is your transcript:", file=file)
        except:
            pass

        await channel.delete(reason="Closed via /close-request by owner")
        await interaction.followup.send("Ticket has been closed successfully.", ephemeral=True)


@bot.tree.command(name="close-request", description="Request the ticket owner to close the ticket")
async def close_request(i: discord.Interaction):
    if "ticket-" not in i.channel.name.lower():
        return await i.response.send_message(
            embed=create_embed(title="❌ Error", 
                             description="This command can only be used inside tickets.", 
                             color=ERROR_COLOR, 
                             guild=i.guild),
            ephemeral=True
        )

    # Ticket Owner finden
    owner = None
    async for msg in i.channel.history(limit=100, oldest_first=True):
        if msg.author != i.guild.me and not msg.author.bot:
            owner = msg.author
            break

    if not owner:
        return await i.response.send_message("Could not find ticket owner.", ephemeral=True)

    embed = create_embed(
        title="🔒 Close Ticket Request",
        description="A staff member has requested to close this ticket.\nPlease confirm below if you are ready to close it.",
        color=0xffaa00,
        guild=i.guild
    )
    embed.add_field(name="Requested by", value=i.user.mention, inline=True)

    view = CloseRequestView(i.channel.id, owner.id)

    await i.response.send_message(embed=embed, view=view)

    # DM an Owner
    try:
        dm_embed = create_embed(
            title="🔒 Close Request",
            description=f"A staff member has requested to close your ticket: **{i.channel.name}**.\n\nClick the button below to accept and close the ticket.",
            color=0xffaa00,
            guild=i.guild
        )
        dm_embed.add_field(name="Ticket", value=i.channel.mention, inline=False)
        
        await owner.send(embed=dm_embed, view=view)
        await i.followup.send(f"✅ Close request sent to {owner.mention} via DM and in ticket.", ephemeral=True)
    except:
        await i.followup.send("Close request sent in ticket, but could not DM the owner.", ephemeral=True)


# ==============================================
# BOT STATS
# ==============================================

@bot.tree.command(name="stats", description="Show bot statistics")
async def stats(interaction: discord.Interaction):
    embed = create_embed(title="Bot Statistics", color=MAIN_COLOR, guild=interaction.guild)
    embed.add_field(name="Guilds", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Users", value=str(len(bot.users)), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)} ms", inline=True)
    embed.add_field(name="Uptime", value="Calculating...", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==============================================
# START BOT
# ==============================================

@bot.event
async def on_ready():
    load_data()
    print(f"Bot online → {bot.user} 🚀")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(f"Sync error: {e}")

    try:
        await refresh_all_panels()
        print("Panels refreshed")
    except Exception as e:
        print(f"Refresh error: {e}")

    if STATUS_ENABLED:
        rotate_status.start()
        print("Status rotation started")

    print("Bot ready!")


if __name__ == "__main__":
    bot.run(TOKEN)