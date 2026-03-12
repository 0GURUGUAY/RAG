-- CEIBO CLOUD USERS - Phone + Telegram alert settings

alter table if exists public.allowed_users
    add column if not exists phone text,
    add column if not exists telegram_chat_id text,
    add column if not exists telegram_alerts_enabled boolean;

update public.allowed_users
set
    phone = coalesce(phone, ''),
    telegram_chat_id = coalesce(telegram_chat_id, ''),
    telegram_alerts_enabled = coalesce(telegram_alerts_enabled, true)
where phone is null
   or telegram_chat_id is null
   or telegram_alerts_enabled is null;

alter table if exists public.allowed_users
    alter column phone set default '',
    alter column telegram_chat_id set default '',
    alter column telegram_alerts_enabled set default true;
