create table settings(id int primary key default 1, ticker text default 'স্বাগতম!', bot_username text, admin_tg text, fb text, tg_channel text, adsterra_link text, adsterra_script text, success_tg text);
insert into settings(id) values(1);
create table profiles(id uuid primary key references auth.users on delete cascade, email text, tg_username text, status text default 'pending', is_admin bool default false, notified bool default false, created_at timestamptz default now());
create table posts(id bigserial primary key, title text not null, descr text, tags text, category text default 'video', type text default 'normal', thumb text, views int default 0, clicks int default 0, impressions int default 0, created_at timestamptz default now());
create table post_links(post_id bigint primary key references posts on delete cascade, direct_link text, tg_msg_id bigint);
create table ads(id bigserial primary key, kind text, image_url text, link text, clicks int default 0, expires_at timestamptz, active bool default true);
create table bot_deletes(id bigserial primary key, chat_id bigint, message_id bigint, delete_at timestamptz);

create function is_admin() returns bool language sql security definer set search_path=public as $$ select coalesce((select is_admin from profiles where id=auth.uid()),false) $$;
create function handle_new_user() returns trigger language plpgsql security definer set search_path=public as $$
begin insert into profiles(id,email,tg_username) values(new.id,new.email,new.raw_user_meta_data->>'tg'); return new; end $$;
create trigger on_signup after insert on auth.users for each row execute function handle_new_user();

create function get_link(pid bigint) returns json language plpgsql security definer set search_path=public as $$
declare p posts; st text; l post_links;
begin select * into p from posts where id=pid; select status into st from profiles where id=auth.uid();
 if st='disabled' then raise exception 'disabled'; end if;
 if p.type='premium' and coalesce(st,'')<>'approved' then raise exception 'locked'; end if;
 select * into l from post_links where post_id=pid; update posts set clicks=clicks+1 where id=pid;
 return json_build_object('direct',l.direct_link,'tg',l.tg_msg_id); end $$;
create function hit(pid bigint, k text) returns void language sql security definer set search_path=public as $$ update posts set views=views+(k='view')::int where id=pid $$;
create function imp(ids bigint[]) returns void language sql security definer set search_path=public as $$ update posts set impressions=impressions+1 where id=any(ids) $$;
create function ad_click(aid bigint) returns void language sql security definer set search_path=public as $$ update ads set clicks=clicks+1 where id=aid $$;
create function delete_user(uid uuid) returns void language plpgsql security definer set search_path=public as $$
begin if not is_admin() then raise exception 'no'; end if; delete from auth.users where id=uid; end $$;

alter table settings enable row level security; alter table profiles enable row level security; alter table posts enable row level security; alter table post_links enable row level security; alter table ads enable row level security; alter table bot_deletes enable row level security;
create policy s_r on settings for select using(true); create policy s_w on settings for all using(is_admin());
create policy p_r on posts for select using(true); create policy p_w on posts for all using(is_admin());
create policy a_r on ads for select using(true); create policy a_w on ads for all using(is_admin());
create policy l_w on post_links for all using(is_admin());
create policy u_own on profiles for select using(id=auth.uid() or is_admin()); create policy u_w on profiles for all using(is_admin());
grant execute on function get_link,hit,imp,ad_click,delete_user to anon,authenticated;

insert into storage.buckets(id,name,public) values('images','images',true) on conflict do nothing;
create policy img_read on storage.objects for select using(bucket_id='images');
create policy img_write on storage.objects for insert with check(bucket_id='images' and public.is_admin());
create policy img_del on storage.objects for delete using(bucket_id='images' and public.is_admin());

-- নিজেকে অ্যাডমিন বানান (আগে সাইটে একবার Register করুন, তারপর এই লাইনটি আলাদা করে Run করুন):
-- update profiles set is_admin=true, status='approved' where email='আপনার@email.com';
