-- =====================================================================
-- security_patch.sql  —  Supabase > SQL Editor এ পুরোটা কপি করে একবার Run করুন
-- (আগের schema.sql চালানো থাকতে হবে। আবার চালালেও সমস্যা নেই।)
-- =====================================================================

-- ---------- ১) রক্ষণাবেক্ষণ মোড ----------
alter table settings add column if not exists maintenance bool default false;
alter table settings add column if not exists maintenance_msg text default
'🛠️ ওয়েবসাইটে রক্ষণাবেক্ষণের কাজ চলছে।
খুব দ্রুত সমাধান করা হবে এবং সাইটটি আবার চালু হবে।
সাময়িক অসুবিধার জন্য আমরা আন্তরিকভাবে দুঃখিত। অনুগ্রহ করে কিছুক্ষণ পর আবার ভিজিট করুন।';
update settings set maintenance_msg=
'🛠️ ওয়েবসাইটে রক্ষণাবেক্ষণের কাজ চলছে।
খুব দ্রুত সমাধান করা হবে এবং সাইটটি আবার চালু হবে।
সাময়িক অসুবিধার জন্য আমরা আন্তরিকভাবে দুঃখিত। অনুগ্রহ করে কিছুক্ষণ পর আবার ভিজিট করুন।'
where id=1 and maintenance_msg is null;

create or replace function is_maintenance() returns bool
language sql stable security definer set search_path=public as $$
  select coalesce((select maintenance from settings where id=1),false)
$$;

-- রক্ষণাবেক্ষণ চালু থাকলে অ্যাডমিন ছাড়া কেউ পোস্ট ডেটাও পড়তে পারবে না (সার্ভার-সাইড ব্লক)
drop policy if exists p_r on posts;
create policy p_r on posts for select using (not is_maintenance() or is_admin());

create or replace function get_link(pid bigint) returns json language plpgsql security definer set search_path=public as $$
declare p posts; st text; l post_links;
begin
 if is_maintenance() and not is_admin() then raise exception 'maintenance'; end if;
 select * into p from posts where id=pid; select status into st from profiles where id=auth.uid();
 if st='disabled' then raise exception 'disabled'; end if;
 if p.type='premium' and coalesce(st,'')<>'approved' then raise exception 'locked'; end if;
 select * into l from post_links where post_id=pid; update posts set clicks=clicks+1 where id=pid;
 return json_build_object('direct',l.direct_link,'tg',l.tg_msg_id); end $$;

-- ---------- ২) Telegram username স্যানিটাইজ (প্রিমিয়াম বাইপাস বন্ধ) ----------
-- আগে বট ilike দিয়ে মেলাত; username এর "_" ওয়াইল্ডকার্ড হয়ে অন্যের প্রিমিয়াম খুলে দিতে পারত।
update profiles set tg_username = nullif(left(lower(regexp_replace(coalesce(tg_username,''),'[^A-Za-z0-9_]','','g')),32),'');

create or replace function handle_new_user() returns trigger language plpgsql security definer set search_path=public as $$
begin
  insert into profiles(id,email,tg_username)
  values(new.id,new.email,
         nullif(left(lower(regexp_replace(coalesce(new.raw_user_meta_data->>'tg',''),'[^A-Za-z0-9_]','','g')),32),''));
  return new;
end $$;

alter table profiles drop constraint if exists tg_fmt;
alter table profiles add constraint tg_fmt check (tg_username is null or tg_username ~ '^[a-z0-9_]{1,32}$');

-- ---------- ২.৫) Telegram অ্যাকাউন্ট যাচাই (/link কোড পদ্ধতি) ----------
-- ইউজার সাইটে লগইন করে কোড নেয়, বটে /link কোড পাঠায় → বট তার আসল Telegram ID প্রোফাইলে বসায়।
-- ফলে username বদলে বা নকল করে প্রিমিয়াম নেওয়া যায় না।
alter table profiles add column if not exists tg_id bigint;
alter table profiles add column if not exists link_code text;
alter table profiles add column if not exists link_code_exp timestamptz;
create unique index if not exists profiles_tg_id_uq on profiles(tg_id) where tg_id is not null;

create or replace function make_link_code() returns text
language plpgsql security definer set search_path=public as $$
declare c text;
begin
  if auth.uid() is null then raise exception 'login'; end if;
  c := upper(substr(replace(gen_random_uuid()::text,'-',''),1,10));
  update profiles set link_code=c, link_code_exp=now()+interval '10 minutes' where id=auth.uid();
  return c;
end $$;
revoke execute on function make_link_code() from public, anon;
grant execute on function make_link_code() to authenticated;

-- ---------- ৩) কাউন্টার অপব্যবহার কমানো ----------
create or replace function imp(ids bigint[]) returns void language sql security definer set search_path=public as $$
  update posts set impressions=impressions+1 where id=any(ids[1:20])
$$;

-- ---------- ৪) অ্যাডমিন নিজেকে ডিলিট করে লক-আউট হওয়া ঠেকানো ----------
create or replace function delete_user(uid uuid) returns void language plpgsql security definer set search_path=public as $$
begin
  if not is_admin() then raise exception 'no'; end if;
  if uid = auth.uid() then raise exception 'নিজেকে ডিলিট করা যাবে না'; end if;
  delete from auth.users where id=uid;
end $$;

-- ---------- ৫) ছবির বাকেট: শুধু ছবি, সর্বোচ্চ ৩ MB (SVG/HTML আপলোড বন্ধ) ----------
update storage.buckets
   set file_size_limit=3145728,
       allowed_mime_types=array['image/jpeg','image/png','image/webp','image/gif']
 where id='images';
