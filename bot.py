import discord
from discord.ext import commands, tasks
import json
import os
import asyncio

# ---------- Загрузка конфигурации ----------
def load_config():
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()
TOKEN = os.getenv('DISCORD_TOKEN')  # Токен из переменных окружения Railway
if not TOKEN:
    raise ValueError("Не задан DISCORD_TOKEN в переменных окружения!")

# Настройки из конфига
GUILD_MP_ID = config['guild_mp_id']
LOG_CHANNEL_ID = config['log_channel_id']
FACTIONS = config['factions']  # словарь вида {"ФСБ": {"role_mp": "ФСБ", "guild_faction": 123, "role_faction": "сотрудник фсб"}, ...}
CHECK_INTERVAL_HOURS = config.get('check_interval_hours', 12)

# ---------- Инициализация бота ----------
intents = discord.Intents.default()
intents.members = True          # Чтобы видеть участников всех серверов
intents.message_content = True  # Для обработки команд с префиксом

bot = commands.Bot(command_prefix='!', intents=intents)

# ---------- Функция логирования ----------
async def log_message(message: str):
    """Отправляет сообщение в канал логов."""
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        await channel.send(message)
    else:
        print(f"LOG: {message}")  # дублируем в консоль

# ---------- Задача проверки каждые 12 часов ----------
@tasks.loop(hours=CHECK_INTERVAL_HOURS)
async def check_roles():
    """Проверяет всех участников МП на наличие ролей фракций и сверяет с серверами фракций."""
    guild_mp = bot.get_guild(GUILD_MP_ID)
    if not guild_mp:
        await log_message("❌ Ошибка: не найден сервер Мероприятий (проверьте ID)")
        return

    for faction_name, faction_data in FACTIONS.items():
        role_mp_name = faction_data['role_mp']
        guild_faction_id = faction_data['guild_faction']
        role_faction_name = faction_data['role_faction']

        guild_faction = bot.get_guild(guild_faction_id)
        if not guild_faction:
            await log_message(f"⚠️ Сервер фракции {faction_name} не найден (ID: {guild_faction_id})")
            continue

        role_mp = discord.utils.get(guild_mp.roles, name=role_mp_name)
        if not role_mp:
            await log_message(f"⚠️ Роль {role_mp_name} не найдена на сервере МП")
            continue

        role_faction = discord.utils.get(guild_faction.roles, name=role_faction_name)
        if not role_faction:
            await log_message(f"⚠️ Роль {role_faction_name} не найдена на сервере {faction_name}")
            continue

        # Перебираем участников сервера МП, у которых есть роль фракции
        for member in guild_mp.members:
            if role_mp in member.roles:
                # Проверяем, есть ли этот пользователь на сервере фракции
                member_faction = guild_faction.get_member(member.id)
                if member_faction is None:
                    # Пользователь не состоит на сервере фракции -> снимаем роль
                    await member.remove_roles(role_mp)
                    await log_message(f"🔻 Снята роль {role_mp_name} с {member.mention} (не состоит в {faction_name})")
                    continue

                # Проверяем наличие роли фракции у пользователя
                if role_faction not in member_faction.roles:
                    await member.remove_roles(role_mp)
                    await log_message(f"🔻 Снята роль {role_mp_name} с {member.mention} (нет роли {role_faction_name} в {faction_name})")
                # else: всё в порядке, ничего не делаем

# ---------- Команда: выдать роль на МП (быстрая выдача) ----------
@bot.command(name='give')
async def give_role(ctx, member: discord.Member, faction_name: str):
    """
    Выдаёт роль указанной фракции участнику на сервере МП.
    Использование: !give @участник ФСБ
    """
    if ctx.guild.id != GUILD_MP_ID:
        await ctx.send("❌ Эта команда работает только на сервере Мероприятий!")
        return

    # Проверяем, существует ли такая фракция
    if faction_name not in FACTIONS:
        await ctx.send(f"❌ Фракция '{faction_name}' не найдена в конфиге. Доступны: {', '.join(FACTIONS.keys())}")
        return

    faction_data = FACTIONS[faction_name]
    role_mp_name = faction_data['role_mp']
    guild_faction_id = faction_data['guild_faction']
    role_faction_name = faction_data['role_faction']

    # Ищем роль на МП
    role_mp = discord.utils.get(ctx.guild.roles, name=role_mp_name)
    if not role_mp:
        await ctx.send(f"❌ Роль {role_mp_name} не найдена на этом сервере. Обратитесь к администратору.")
        return

    # Проверяем, есть ли участник на сервере фракции и имеет ли нужную роль
    guild_faction = bot.get_guild(guild_faction_id)
    if not guild_faction:
        await ctx.send(f"❌ Сервер фракции {faction_name} не найден (ID: {guild_faction_id})")
        return

    member_faction = guild_faction.get_member(member.id)
    if member_faction is None:
        await ctx.send(f"❌ Участник {member.mention} не состоит на сервере {faction_name}!")
        return

    role_faction = discord.utils.get(guild_faction.roles, name=role_faction_name)
    if not role_faction:
        await ctx.send(f"❌ Роль {role_faction_name} не найдена на сервере {faction_name}")
        return

    if role_faction not in member_faction.roles:
        await ctx.send(f"❌ Участник {member.mention} не имеет роли {role_faction_name} на сервере {faction_name}!")
        return

    # Всё ок, выдаём роль на МП
    if role_mp in member.roles:
        await ctx.send(f"ℹ️ Участник {member.mention} уже имеет роль {role_mp_name}.")
    else:
        await member.add_roles(role_mp)
        await ctx.send(f"✅ Выдана роль {role_mp_name} участнику {member.mention} (фракция {faction_name}).")
        await log_message(f"✅ {ctx.author.mention} выдал роль {role_mp_name} {member.mention} (фракция {faction_name})")

# ---------- Команда: перезагрузить конфиг (без перезапуска) ----------
@bot.command(name='reload_config')
@commands.has_permissions(administrator=True)
async def reload_config(ctx):
    """Перезагружает config.json (только для администраторов)."""
    global config, FACTIONS, GUILD_MP_ID, LOG_CHANNEL_ID, CHECK_INTERVAL_HOURS
    try:
        config = load_config()
        FACTIONS = config['factions']
        GUILD_MP_ID = config['guild_mp_id']
        LOG_CHANNEL_ID = config['log_channel_id']
        CHECK_INTERVAL_HOURS = config.get('check_interval_hours', 12)
        # Если интервал изменился, перезапускаем задачу
        check_roles.change_interval(hours=CHECK_INTERVAL_HOURS)
        await ctx.send("✅ Конфигурация перезагружена!")
        await log_message("🔄 Конфигурация перезагружена администратором.")
    except Exception as e:
        await ctx.send(f"❌ Ошибка при перезагрузке: {e}")

# ---------- Событие готовности ----------
@bot.event
async def on_ready():
    print(f'Бот {bot.user} запущен!')
    await log_message(f'✅ Бот запущен и готов к работе!')
    check_roles.start()  # запускаем периодическую задачу

# ---------- Запуск ----------
if __name__ == '__main__':
    bot.run(TOKEN)
