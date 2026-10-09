import os
import io
import json
import discord
from discord.ext import commands

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def read_secret(env_name: str, filename: str) -> str:
    """อ่านค่าลับจาก Environment Variable ก่อน ถ้าไม่มีให้อ่านจากไฟล์ข้างๆ main.py"""
    value = os.getenv(env_name)
    if value:
        return value.strip()
    try:
        with open(os.path.join(BASE_DIR, filename), "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


TOKEN = read_secret("DISCORD_TOKEN", "token.txt")
OWNER_ID = int(read_secret("OWNER_ID", "owner_id.txt") or 0)  # ไม่บังคับ: ใส่ ID ของคุณถ้าไม่ใช่เจ้าของเซิร์ฟเวอร์
MAX_FILE_BYTES = 25 * 1024 * 1024
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ค่าเริ่มต้นของเมนู (แก้ในดิสได้ด้วย /setmenu และ /setmenu_more)
DEFAULT_CONFIG = {
    "title": "🔍 เช็คคนไม่ฟอลกลับ",
    "description": (
        "1. โหลดข้อมูลจาก Instagram (ผู้ติดตามและกำลังติดตาม, รูปแบบ JSON)\n"
        "2. กดปุ่มด้านล่าง แล้วอัปโหลดไฟล์ followers และ following\n"
        "3. บอทจะแสดงจำนวนและส่งรายชื่อเป็นไฟล์ให้"
    ),
    "color": "5865F2",
    "image": "",
    "thumbnail": "",
    "footer": "Rank Bot",
    "button": "อัปโหลดไฟล์เพื่อเช็ค",
    "menus": [],  # เมนูที่ส่งไว้แล้ว [[channel_id, message_id], ...]
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def is_owner(interaction: discord.Interaction) -> bool:
    return bool(
        (interaction.guild and interaction.user.id == interaction.guild.owner_id)
        or interaction.user.id == OWNER_ID
    )


def parse_color(text: str) -> int:
    return int(text.strip().lstrip("#"), 16)


def valid_url(text: str) -> bool:
    return text == "" or text.startswith(("http://", "https://"))


# ---------------- เช็คคนไม่ฟอลกลับ ----------------
def extract_usernames(data) -> set:
    """ดึงชื่อบัญชีจากไฟล์ JSON ของ Instagram (ทั้ง followers และ following)"""
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    names = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        for s in item.get("string_list_data", []):
            if s.get("value"):
                names.add(s["value"].lower())
        if item.get("title"):
            names.add(item["title"].lower())
    return names


async def read_json(att: discord.Attachment):
    if att.size > MAX_FILE_BYTES:
        raise ValueError(f"ไฟล์ {att.filename} ใหญ่เกินไป")
    raw = await att.read()
    return json.loads(raw.decode("utf-8"))


class UploadModal(discord.ui.Modal, title="อัปโหลดไฟล์จาก Instagram"):
    followers_up = discord.ui.Label(
        text="ไฟล์ followers (followers_1.json ...)",
        component=discord.ui.FileUpload(custom_id="followers_up", min_values=1, max_values=10),
    )
    following_up = discord.ui.Label(
        text="ไฟล์ following (following.json)",
        component=discord.ui.FileUpload(custom_id="following_up", min_values=1, max_values=1),
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            followers = set()
            for att in self.followers_up.component.values:
                followers |= extract_usernames(await read_json(att))
            following = set()
            for att in self.following_up.component.values:
                following |= extract_usernames(await read_json(att))
        except Exception as e:
            return await interaction.followup.send(
                f"❌ อ่านไฟล์ไม่ได้ ตรวจสอบว่าเป็นไฟล์ JSON จาก Instagram ({e})", ephemeral=True
            )

        if not followers or not following:
            return await interaction.followup.send(
                "❌ ไม่พบรายชื่อในไฟล์ ลองเช็คว่าอัปโหลดไฟล์ถูกช่องหรือยัง", ephemeral=True
            )

        result = sorted(following - followers)
        text = "\n".join(result) if result else "(ไม่มี)"
        file = discord.File(io.BytesIO(text.encode("utf-8")), filename="not_following_back.txt")
        await interaction.followup.send(
            f"✅ ผู้ติดตาม: {len(followers)} | กำลังติดตาม: {len(following)}\n"
            f"👎 คนที่ไม่ฟอลกลับ: **{len(result)}** บัญชี",
            file=file,
            ephemeral=True,
        )


# ---------------- เมนู ----------------
def build_menu_embed() -> discord.Embed:
    cfg = load_config()
    try:
        color = parse_color(cfg["color"])
    except ValueError:
        color = 0x5865F2
    embed = discord.Embed(title=cfg["title"], description=cfg["description"], color=color)
    if cfg["image"]:
        embed.set_image(url=cfg["image"])
    if cfg["thumbnail"]:
        embed.set_thumbnail(url=cfg["thumbnail"])
    if cfg["footer"]:
        embed.set_footer(text=cfg["footer"])
    return embed


class MenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.check.label = load_config()["button"]

    @discord.ui.button(label="เช็ค", style=discord.ButtonStyle.primary,
                       emoji="📂", custom_id="check_unfollowers")
    async def check(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UploadModal())


async def refresh_menus() -> int:
    """อัปเดตเมนูที่ส่งค้างไว้ทุกช่องให้ตรงกับการตั้งค่าล่าสุด"""
    cfg = load_config()
    alive, updated = [], 0
    for channel_id, message_id in cfg["menus"]:
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            await channel.get_partial_message(message_id).edit(
                embed=build_menu_embed(), view=MenuView()
            )
            alive.append([channel_id, message_id])
            updated += 1
        except discord.NotFound:
            continue  # ข้อความถูกลบแล้ว
        except Exception:
            alive.append([channel_id, message_id])
    cfg["menus"] = alive
    save_config(cfg)
    return updated


class EditMenuModal(discord.ui.Modal, title="ปรับแต่งหน้าเมนู"):
    title_in = discord.ui.TextInput(label="หัวข้อ", max_length=200)
    desc_in = discord.ui.TextInput(label="ข้อความอธิบาย", style=discord.TextStyle.paragraph,
                                   max_length=1500)
    color_in = discord.ui.TextInput(label="สี (รหัส HEX เช่น 5865F2)", max_length=7)
    image_in = discord.ui.TextInput(label="ลิงก์รูปใหญ่ (เว้นว่าง = ไม่มีรูป)",
                                    required=False, max_length=500)
    footer_in = discord.ui.TextInput(label="ข้อความท้ายเมนู", required=False, max_length=100)

    def __init__(self):
        super().__init__()
        cfg = load_config()
        self.title_in.default = cfg["title"]
        self.desc_in.default = cfg["description"]
        self.color_in.default = cfg["color"]
        self.image_in.default = cfg["image"]
        self.footer_in.default = cfg["footer"]

    async def on_submit(self, interaction: discord.Interaction):
        try:
            parse_color(self.color_in.value)
        except ValueError:
            return await interaction.response.send_message(
                "❌ รหัสสีไม่ถูกต้อง ใส่แบบ 5865F2 หรือ #5865F2", ephemeral=True)
        if not valid_url(self.image_in.value.strip()):
            return await interaction.response.send_message(
                "❌ ลิงก์รูปต้องขึ้นต้นด้วย http:// หรือ https://", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        cfg = load_config()
        cfg.update(
            title=self.title_in.value,
            description=self.desc_in.value,
            color=self.color_in.value.strip().lstrip("#"),
            image=self.image_in.value.strip(),
            footer=self.footer_in.value,
        )
        save_config(cfg)
        n = await refresh_menus()
        await interaction.followup.send(f"✅ บันทึกแล้ว อัปเดตเมนูที่ส่งไว้ {n} ช่อง", ephemeral=True)


# ---------------- บอท ----------------
class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        self.add_view(MenuView())
        await self.tree.sync()


bot = Bot()


@bot.tree.command(name="menu", description="ส่งเมนูค้างไว้ในช่องนี้ (เฉพาะเจ้าของ)")
async def menu(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะเจ้าของ", ephemeral=True)
    msg = await interaction.channel.send(embed=build_menu_embed(), view=MenuView())
    cfg = load_config()
    cfg["menus"].append([msg.channel.id, msg.id])
    save_config(cfg)
    await interaction.response.send_message("✅ ส่งเมนูไว้ในช่องนี้แล้ว", ephemeral=True)


@bot.tree.command(name="setmenu", description="แก้หัวข้อ ข้อความ สี รูปใหญ่ ข้อความท้าย (เฉพาะเจ้าของ)")
async def setmenu(interaction: discord.Interaction):
    if not is_owner(interaction):
        return await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะเจ้าของ", ephemeral=True)
    await interaction.response.send_modal(EditMenuModal())


@bot.tree.command(name="setmenu_more", description="แก้รูปเล็กและชื่อปุ่ม (เฉพาะเจ้าของ)")
@discord.app_commands.describe(
    thumbnail="ลิงก์รูปเล็กมุมขวาบน (พิมพ์ - เพื่อลบรูป)",
    button="ข้อความบนปุ่ม",
)
async def setmenu_more(interaction: discord.Interaction, thumbnail: str = None, button: str = None):
    if not is_owner(interaction):
        return await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะเจ้าของ", ephemeral=True)
    cfg = load_config()
    if thumbnail is not None:
        thumbnail = "" if thumbnail.strip() == "-" else thumbnail.strip()
        if not valid_url(thumbnail):
            return await interaction.response.send_message(
                "❌ ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https://", ephemeral=True)
        cfg["thumbnail"] = thumbnail
    if button is not None:
        cfg["button"] = button[:80]
    save_config(cfg)
    await interaction.response.defer(ephemeral=True)
    n = await refresh_menus()
    await interaction.followup.send(f"✅ บันทึกแล้ว อัปเดตเมนูที่ส่งไว้ {n} ช่อง", ephemeral=True)


if not TOKEN:
    raise SystemExit("ไม่พบ token: ตั้ง DISCORD_TOKEN หรือสร้างไฟล์ token.txt ข้างๆ main.py")
bot.run(TOKEN)
