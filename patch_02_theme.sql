-- patch_02_theme.sql — Supabase > SQL Editor এ একবার Run করুন (থিম বদলের অপশনের জন্য)
alter table settings add column if not exists theme text default 'neon';
update settings set theme='neon' where id=1 and theme is null;
alter table settings drop constraint if exists theme_ok;
alter table settings add constraint theme_ok check (theme in ('neon','sunset','ocean','light'));
