"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { BadgeCheck, BarChart3, Bell, CalendarDays, CircleDollarSign, Copy, FileText, Headphones, LogOut, Megaphone, Plus, Settings, TrendingUp, WalletCards } from "lucide-react";
import { api, clearSession, getSessionUser, SessionUser } from "@/lib/api";

type Campaign={id:number;title:string;status:string;preferred_publish_at?:string|null;facebook_post_url?:string|null;created_at:string};
type Notification={id:number;read_at?:string|null};
type Payment={id:number;campaign_id:number;amount:number;currency:string;status:string};

export default function AdvertiserDashboard(){
  const router=useRouter();
  const [user,setUser]=useState<SessionUser|null>(null);
  const [campaigns,setCampaigns]=useState<Campaign[]>([]);
  const [notifications,setNotifications]=useState<Notification[]>([]);
  const [payments,setPayments]=useState<Payment[]>([]);
  const [loading,setLoading]=useState(true);
  const [duplicating,setDuplicating]=useState<number|null>(null);

  useEffect(()=>{
    const current=getSessionUser();
    if(!current||current.role!=="advertiser"){router.replace("/login");return;}
    setUser(current);
    Promise.all([api<Campaign[]>("/api/v1/campaigns",{},true),api<Notification[]>("/api/v1/notifications",{},true)])
      .then(async([c,n])=>{
        setCampaigns(c);setNotifications(n);
        const rows=await Promise.all(c.map(item=>api<Payment[]>(`/api/v1/campaigns/${item.id}/payments`,{},true).catch(()=>[])));
        setPayments(rows.flat());
      }).catch(()=>{}).finally(()=>setLoading(false));
  },[router]);

  const stats=useMemo(()=>{
    const inProgress=campaigns.filter(c=>["payment_pending","submitted","in_review","changes_requested"].includes(c.status)).length;
    const approved=campaigns.filter(c=>["approved","scheduled","published"].includes(c.status)).length;
    const published=campaigns.filter(c=>c.status==="published").length;
    const paid=payments.filter(p=>p.status==="paid");
    const spend=paid.reduce((sum,p)=>sum+Number(p.amount||0),0);
    const paidCampaigns=new Set(paid.map(p=>p.campaign_id)).size;
    const publishRate=campaigns.length?Math.round((published/campaigns.length)*100):0;
    const approvalRate=campaigns.length?Math.round((approved/campaigns.length)*100):0;
    return {all:campaigns.length,inProgress,approved,published,spend,paidCampaigns,publishRate,approvalRate};
  },[campaigns,payments]);

  const unread=notifications.filter(n=>!n.read_at).length;
  async function duplicate(id:number){setDuplicating(id);try{const result=await api<{id:number}>(`/api/v1/campaigns/${id}/duplicate`,{method:"POST"},true);router.push(`/advertiser/billing?campaign=${result.id}`);}finally{setDuplicating(null);}}
  function logout(){clearSession();router.push("/login");}
  if(!user)return <main className="grid min-h-screen place-items-center bg-[#f5f6fa] text-sm font-bold text-slate-500">Opening your workspace...</main>;

  return <main className="min-h-screen bg-[#f5f6fa] text-slate-900">
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="mx-auto flex h-18 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8"><Link href="/advertiser" className="flex min-w-0 items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[#070a45] text-white"><Megaphone size={18}/></div><div className="min-w-0"><div className="truncate text-sm font-black tracking-tight text-[#070a45]">MELOLI<span className="text-[#e31545]">AIRWAVES</span></div><div className="text-[10px] font-bold uppercase tracking-[.16em] text-slate-400">Advertiser Portal</div></div></Link><nav className="ml-auto hidden items-center gap-1 md:flex"><Nav href="/advertiser" label="Overview"/><Nav href="/advertiser/performance" label="Performance"/><Nav href="/advertiser/new" label="Create advert"/><Nav href="/advertiser/billing" label="Payments & documents"/><Nav href="/advertiser/support" label="Support"/><Nav href="/advertiser/account" label="Account"/><Nav href="/advertiser/notifications" label={`Notifications${unread?` (${unread})`:""}`}/></nav><Link href="/advertiser/notifications" className="relative ml-auto grid h-10 w-10 place-items-center rounded-xl border border-slate-200 text-slate-500 md:hidden"><Bell size={17}/>{unread>0&&<span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-[#e31545]"/>}</Link><button onClick={logout} className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 text-slate-500 md:ml-2" title="Sign out"><LogOut size={17}/></button></div></header>

    <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      <section className="overflow-hidden rounded-[1.8rem] bg-[#070a45] p-6 text-white sm:p-8"><div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between"><div><p className="text-xs font-black uppercase tracking-[.2em] text-white/45">Advertiser workspace</p><h1 className="mt-2 text-3xl font-black sm:text-4xl">Welcome, {user.full_name.split(" ")[0]}.</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-white/60">Create campaigns, respond to editorial feedback and measure your advertising activity from payment through publication.</p></div><Link href="/advertiser/new" className="inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-[#e31545] px-5 text-sm font-extrabold shadow-lg shadow-rose-950/20"><Plus size={18}/> Create new advert</Link></div></section>

      <section className="mt-6"><div className="mb-3 flex items-end justify-between"><div><p className="text-xs font-black uppercase tracking-[.16em] text-[#e31545]">My KPIs</p><h2 className="mt-1 text-xl font-black text-[#070a45]">Advertising performance at a glance</h2></div><Link href="/advertiser/performance" className="hidden text-xs font-extrabold text-[#e31545] sm:block">Open audience performance →</Link></div><div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Metric icon={<Megaphone/>} label="All adverts" value={String(stats.all)} detail={`${stats.inProgress} currently in progress`}/><Metric icon={<CircleDollarSign/>} label="Confirmed spend" value={`M ${stats.spend.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`} detail={`${stats.paidCampaigns} paid campaign${stats.paidCampaigns===1?"":"s"}`}/><Metric icon={<BadgeCheck/>} label="Approval rate" value={`${stats.approvalRate}%`} detail={`${stats.approved} approved, scheduled or published`}/><Metric icon={<TrendingUp/>} label="Publish rate" value={`${stats.publishRate}%`} detail={`${stats.published} live advert${stats.published===1?"":"s"}`}/></div></section>

      <section className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="overflow-hidden rounded-[1.5rem] border border-slate-200 bg-white"><div className="flex items-center justify-between border-b border-slate-100 p-5 sm:p-6"><div><h2 className="font-black text-[#070a45]">My advertising campaigns</h2><p className="mt-1 text-sm text-slate-500">Your latest submissions and their current status.</p></div><Link href="/advertiser/new" className="text-sm font-extrabold text-[#e31545]">New advert</Link></div>{loading?<div className="p-8 text-sm text-slate-500">Loading campaigns...</div>:campaigns.length===0?<Empty/>:<div className="divide-y divide-slate-100">{campaigns.map(c=><article key={c.id} className="grid gap-3 p-5 sm:grid-cols-[1fr_auto] sm:items-center sm:px-6"><div><div className="flex flex-wrap items-center gap-2"><h3 className="font-extrabold text-slate-900">{c.title}</h3><Status value={c.status}/></div><p className="mt-2 text-xs font-semibold text-slate-400">Created {new Date(c.created_at).toLocaleDateString()} {c.preferred_publish_at?`· Preferred ${new Date(c.preferred_publish_at).toLocaleString()}`:""}</p></div><div className="flex items-center gap-2">{c.facebook_post_url?<a className="text-sm font-extrabold text-[#070a45]" href={c.facebook_post_url} target="_blank">Open post</a>:<span className="text-xs font-bold text-slate-400">#{c.id}</span>}<button disabled={duplicating===c.id} onClick={()=>duplicate(c.id)} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-extrabold text-slate-600 disabled:opacity-50"><Copy size={13}/>{duplicating===c.id?"Copying":"Run again"}</button></div></article>)}</div>}</div>
        <aside className="space-y-4"><Quick href="/advertiser/performance" icon={<BarChart3/>} title="Audience performance" text="See reach, impressions, clicks, reactions, comments and shares for published adverts."/><Quick href="/advertiser/billing" icon={<WalletCards/>} title="Payments & receipts" text="Track payment verification and download PDF receipts after Meloli confirms payment."/><Quick href="/advertiser/notifications" icon={<Bell/>} title={`Notifications${unread?` · ${unread} unread`:""}`} text="See payment, editorial and publishing updates from Meloli."/><Quick href="/advertiser/support" icon={<Headphones/>} title="Support centre" text="Ask Meloli about a campaign, payment or account issue and keep replies in one place."/><Quick href="/advertiser/notifications" icon={<FileText/>} title="Editorial feedback" text="Change requests and approval decisions stay visible and traceable."/><Quick href="/advertiser/account" icon={<Settings/>} title="My account" text={user.business_name||user.email}/></aside>
      </section>
    </div>
  </main>;
}

function Nav({href,label}:{href:string;label:string}){return <Link href={href} className="rounded-xl px-3 py-2 text-sm font-bold text-slate-500 hover:bg-slate-50 hover:text-[#070a45]">{label}</Link>}
function Metric({icon,label,value,detail}:{icon:React.ReactNode;label:string;value:string;detail:string}){return <div className="rounded-[1.35rem] border border-slate-200 bg-white p-4 sm:p-5"><div className="text-[#e31545] [&>svg]:h-5 [&>svg]:w-5">{icon}</div><p className="mt-4 break-words text-2xl font-black text-[#070a45] sm:text-3xl">{value}</p><p className="mt-1 text-xs font-bold text-slate-600 sm:text-sm">{label}</p><p className="mt-2 text-[11px] font-semibold leading-4 text-slate-400">{detail}</p></div>}
function Status({value}:{value:string}){const map:Record<string,string>={published:"bg-emerald-50 text-emerald-700",approved:"bg-blue-50 text-blue-700",scheduled:"bg-indigo-50 text-indigo-700",changes_requested:"bg-rose-50 text-rose-700",rejected:"bg-rose-50 text-rose-700",in_review:"bg-amber-50 text-amber-700",payment_pending:"bg-slate-100 text-slate-600",submitted:"bg-violet-50 text-violet-700",draft:"bg-slate-100 text-slate-600"};return <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${map[value]||"bg-slate-100 text-slate-600"}`}>{value.replaceAll("_"," ")}</span>}
function Empty(){return <div className="p-8 text-center sm:p-12"><div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-[#070a45]/5 text-[#070a45]"><Megaphone/></div><h3 className="mt-4 font-black text-[#070a45]">No campaigns yet</h3><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">Your first advert will appear here and remain traceable through payment, review and publication.</p><Link href="/advertiser/new" className="mt-5 inline-flex rounded-xl bg-[#e31545] px-4 py-3 text-sm font-extrabold text-white">Create first advert</Link></div>}
function Quick({href,icon,title,text}:{href:string;icon:React.ReactNode;title:string;text:string}){return <Link href={href} className="block rounded-[1.35rem] border border-slate-200 bg-white p-5 transition hover:border-slate-300 hover:shadow-sm"><div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[#070a45]/5 text-[#070a45] [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</div><h3 className="font-black text-[#070a45]">{title}</h3></div><p className="mt-3 text-sm leading-6 text-slate-500">{text}</p></Link>}
