-- patch_03_tokens_search_indexes.sql
-- Supabase > SQL Editor এ পুরোটা একসাথে Run করুন। বারবার চালালেও সমস্যা নেই।
-- ডিপ্লয়ের ক্রম: ১) এই SQL  ২) index.html, post.html, admin.html  ৩) bot.py

-- ============================================================
-- ১. পোস্ট লিস্ট ও বটের লুকআপ দ্রুত করার ইনডেক্স
-- ============================================================
create index if not exists posts_created_idx on posts(created_at desc);
create index if not exists posts_cat_type_idx on posts(category, type, created_at desc);
create index if not exists links_tgmsg_idx on post_links(tg_msg_id);
create index if not exists prof_tgid_idx on profiles(tg_id);
create index if not exists prof_tguser_idx on profiles(tg_username);

-- ============================================================
-- ২. পুরনো ইউজারদের Telegram ইউজারনেম ছোট হাতের ও ট্রিম করা
--    (নতুন রেজিস্ট্রেশনে সাইটই এটা করে দেয়)
-- ============================================================
update profiles
set tg_username = lower(trim(tg_username))
where tg_username is not null;

-- ============================================================
-- ৩. একবার-ব্যবহারযোগ্য ডাউনলোড টোকেন (বটের ডিপ-লিংক সুরক্ষা)
-- ============================================================
create table if not exists dl_tokens(
  token text primary key,
  msg_id bigint not null,
  created_at timestamptz default now()
);
-- RLS চালু, কোনো policy নেই: সরাসরি কেউ পড়তে/লিখতে পারবে না।
-- শুধু নিচের security definer ফাংশন আর বট (service key) ব্যবহার করে।
alter table dl_tokens enable row level security;
create index if not exists dl_tokens_created_idx on dl_tokens(created_at);

create or replace function make_dl_token(pid bigint) returns text
language plpgsql security definer set search_path=public as $$
declare p posts; st text; l post_links; t text; mt bool;
begin
  select * into p from posts where id=pid;
  if p.id is null then raise exception 'notfound'; end if;

  select maintenance into mt from settings where id=1;
  if coalesce(mt,false) and not is_admin() then raise exception 'maintenance'; end if;

  select status into st from profiles where id=auth.uid();
  if st='disabled' then raise exception 'disabled'; end if;
  if p.type='premium' and coalesce(st,'')<>'approved' then raise exception 'locked'; end if;

  select * into l from post_links where post_id=pid;
  if l.tg_msg_id is null then return null; end if;

  t := replace(gen_random_uuid()::text,'-','');
  insert into dl_tokens(token,msg_id) values(t,l.tg_msg_id);
  return t;
end $$;

grant execute on function make_dl_token(bigint) to anon,authenticated;

-- ============================================================
-- ৪. সার্চ দ্রুত করার ইনডেক্স (title / tags এ ilike '%শব্দ%')
--    বাংলা লেখায় কতটা কাজ করবে নিশ্চিত নয়; না করলেও সার্চের ফল ঠিক থাকে।
-- ============================================================
create extension if not exists pg_trgm with schema extensions;
create index if not exists posts_title_trgm on posts using gin (title extensions.gin_trgm_ops);
create index if not exists posts_tags_trgm on posts using gin (tags extensions.gin_trgm_ops);

-- ============================================================
-- ৫. (ঐচ্ছিক) Telegram কানেক্ট বাটন সরানোর পর অব্যবহৃত ফাংশন মুছতে চাইলে
--    নিচের লাইনের শুরুর -- সরিয়ে Run করুন। tg_id কলাম মুছবেন না,
--    আগে যারা /link করেছেন তাদের তথ্য ওখানে আছে।
-- ============================================================
-- drop function if exists make_link_code();
