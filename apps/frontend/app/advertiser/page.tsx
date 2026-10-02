"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { BadgeCheck, BarChart3, Bell, CircleDollarSign, Copy, FileText, Headphones, Home, LogOut, Megaphone, Plus, Settings, TrendingUp, WalletCards } from "lucide-react";
import { api, clearSession, getSessionUser, SessionUser } from "@/lib/api";

type Campaign={id:number;title:string;status:string;engagement_mode:string;preferred_publish_at?:string|null;facebook_post_url?:string|null;created_at:string;cancelled_at?:string|null;cancellation_reason?:string|null;proof_status:string;proof_feedback?:string|null};
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

  return <main className="fb-page mobile-safe-bottom">
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white shadow-sm"><div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-3 sm:px-4 lg:px-6"><Link href="/advertiser" className="flex min-w-0 items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-full bg-[#0866ff] text-white"><Megaphone size={18}/></div><div className="min-w-0"><div className="truncate text-[15px] font-bold tracking-tight text-slate-900">MELOLI AIRWAVES</div><div className="text-xs text-[#65676b]">Advertiser Portal</div></div></Link><nav className="ml-auto hidden items-center gap-1 md:flex"><Nav href="/advertiser" label="Overview"/><Nav href="/advertiser/performance" label="Performance"/><Nav href="/advertiser/new" label="Create advert"/><Nav href="/advertiser/billing" label="Payments & documents"/><Nav href="/advertiser/support" label="Support"/><Nav href="/advertiser/account" label="Account"/><Nav href="/advertiser/notifications" label={`Notifications${unread?` (${unread})`:""}`}/></nav><Link href="/advertiser/notifications" className="fb-icon-button relative ml-auto md:hidden"><Bell size={17}/>{unread>0&&<span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-[#0866ff]"/>}</Link><button onClick={logout} className="fb-icon-button md:ml-2" title="Sign out"><LogOut size={17}/></button></div></header>

    <div className="mx-auto max-w-7xl p-3 sm:p-4 lg:p-6">
      <section className="fb-card p-4 sm:p-5"><div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between"><div><p className="text-xs font-black uppercase tracking-[.2em] text-[#65676b]">Advertiser workspace</p><h1 className="mt-1 text-2xl font-bold text-slate-900 sm:text-3xl">Welcome, {user.full_name.split(" ")[0]}.</h1><p className="mt-3 max-w-2xl text-sm leading-6 text-[#65676b]">Create campaigns, respond to editorial feedback and measure your advertising activity from payment through publication.</p></div><Link href="/advertiser/new" className="fb-primary inline-flex h-11 items-center justify-center gap-2 px-5 text-sm"><Plus size={18}/> Create new advert</Link></div></section>

      <section className="mt-6"><div className="mb-3 flex items-end justify-between"><div><p className="text-xs font-black uppercase tracking-[.16em] text-[#0866ff]">My KPIs</p><h2 className="mt-1 text-xl font-black text-slate-900">Advertising performance at a glance</h2></div><Link href="/advertiser/performance" className="hidden text-xs font-extrabold text-[#0866ff] sm:block">Open audience performance →</Link></div><div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><Metric icon={<Megaphone/>} label="All adverts" value={String(stats.all)} detail={`${stats.inProgress} currently in progress`}/><Metric icon={<CircleDollarSign/>} label="Confirmed spend" value={`M ${stats.spend.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`} detail={`${stats.paidCampaigns} paid campaign${stats.paidCampaigns===1?"":"s"}`}/><Metric icon={<BadgeCheck/>} label="Approval rate" value={`${stats.approvalRate}%`} detail={`${stats.approved} approved, scheduled or published`}/><Metric icon={<TrendingUp/>} label="Publish rate" value={`${stats.publishRate}%`} detail={`${stats.published} live advert${stats.published===1?"":"s"}`}/></div></section>

      <section className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="overflow-hidden rounded-[1.5rem] border border-slate-200 bg-white"><div className="flex items-center justify-between border-b border-slate-100 p-5 sm:p-6"><div><h2 className="font-black text-slate-900">My advertising campaigns</h2><p className="mt-1 text-sm text-slate-500">Your latest submissions and their current status.</p></div><Link href="/advertiser/new" className="text-sm font-extrabold text-[#0866ff]">New advert</Link></div>{loading?<div className="p-8 text-sm text-slate-500">Loading campaigns...</div>:campaigns.length===0?<Empty/>:<div className="divide-y divide-slate-100">{campaigns.map(c=><article key={c.id} className="grid gap-3 p-5 sm:grid-cols-[1fr_auto] sm:items-center sm:px-6"><div><div className="flex flex-wrap items-center gap-2"><h3 className="font-extrabold text-slate-900">{c.title}</h3><Status value={c.cancelled_at?"cancelled":c.status}/></div><p className="mt-2 text-xs font-semibold text-slate-400">Created {new Date(c.created_at).toLocaleDateString()} {c.preferred_publish_at?`· Preferred ${new Date(c.preferred_publish_at).toLocaleString()}`:""}</p></div><div className="flex items-center gap-2">{c.facebook_post_url?<a className="text-sm font-extrabold text-slate-900" href={c.facebook_post_url} target="_blank">Open post</a>:<span className="text-xs font-bold text-slate-400">#{c.id}</span>}{c.engagement_mode==="competition_one_comment"&&<Link href={"/campaigns/"+c.id+"/competition"} className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1.5 text-xs font-extrabold text-amber-800">Competition results</Link>}{c.proof_status==="pending_advertiser"&&<Link href={"/advertiser/campaigns/"+c.id+"/proof"} className="rounded-lg bg-[#0866ff] px-2.5 py-1.5 text-xs font-extrabold text-white">Review proof</Link>}{!c.cancelled_at&&c.status!=="published"&&<Link href={"/advertiser/campaigns/"+c.id+"/cancel"} className="rounded-lg border border-rose-200 px-2.5 py-1.5 text-xs font-extrabold text-rose-700">Cancel</Link>}<button disabled={duplicating===c.id} onClick={()=>duplicate(c.id)} className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-extrabold text-slate-600 disabled:opacity-50"><Copy size={13}/>{duplicating===c.id?"Copying":"Run again"}</button></div></article>)}</div>}</div>
        <aside className="space-y-4"><Quick href="/advertiser/performance" icon={<BarChart3/>} title="Audience performance" text="See reach, impressions, clicks, reactions, comments and shares for published adverts."/><Quick href="/advertiser/billing" icon={<WalletCards/>} title="Payments & receipts" text="Track payment verification and download PDF receipts after Meloli confirms payment."/><Quick href="/advertiser/notifications" icon={<Bell/>} title={`Notifications${unread?` · ${unread} unread`:""}`} text="See payment, editorial and publishing updates from Meloli."/><Quick href="/advertiser/support" icon={<Headphones/>} title="Support centre" text="Ask Meloli about a campaign, payment or account issue and keep replies in one place."/><Quick href="/advertiser/notifications" icon={<FileText/>} title="Editorial feedback" text="Change requests and approval decisions stay visible and traceable."/><Quick href="/advertiser/account" icon={<Settings/>} title="My account" text={user.business_name||user.email}/></aside>
      </section>
    </div>
    <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)] shadow-[0_-1px_8px_rgba(0,0,0,.08)] md:hidden"><MobileNav href="/advertiser" icon={<Home/>} label="Home"/><MobileNav href="/advertiser/new" icon={<Plus/>} label="Create"/><MobileNav href="/advertiser/performance" icon={<BarChart3/>} label="Insights"/><MobileNav href="/advertiser/billing" icon={<WalletCards/>} label="Payments"/><MobileNav href="/advertiser/account" icon={<Settings/>} label="Account"/></nav>
  </main>;
}

function Nav({href,label}:{href:string;label:string}){return <Link href={href} className="rounded-lg px-3 py-2 text-sm font-semibold text-[#65676b] hover:bg-[#f2f2f2] hover:text-slate-900">{label}</Link>}
function Metric({icon,label,value,detail}:{icon:React.ReactNode;label:string;value:string;detail:string}){return <div className="fb-card p-4"><div className="text-[#0866ff] [&>svg]:h-5 [&>svg]:w-5">{icon}</div><p className="mt-4 break-words text-2xl font-black text-slate-900 sm:text-3xl">{value}</p><p className="mt-1 text-xs font-bold text-slate-600 sm:text-sm">{label}</p><p className="mt-2 text-[11px] font-semibold leading-4 text-slate-400">{detail}</p></div>}
function Status({value}:{value:string}){const map:Record<string,string>={published:"bg-emerald-50 text-emerald-700",approved:"bg-blue-50 text-blue-700",scheduled:"bg-indigo-50 text-indigo-700",changes_requested:"bg-rose-50 text-rose-700",rejected:"bg-rose-50 text-rose-700",cancelled:"bg-slate-200 text-slate-700",in_review:"bg-amber-50 text-amber-700",payment_pending:"bg-slate-100 text-slate-600",submitted:"bg-violet-50 text-violet-700",draft:"bg-slate-100 text-slate-600"};return <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${map[value]||"bg-slate-100 text-slate-600"}`}>{value.replaceAll("_"," ")}</span>}
function Empty(){return <div className="p-8 text-center sm:p-12"><div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-[#e7f3ff] text-slate-900"><Megaphone/></div><h3 className="mt-4 font-black text-slate-900">No campaigns yet</h3><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">Your first advert will appear here and remain traceable through payment, review and publication.</p><Link href="/advertiser/new" className="mt-5 inline-flex rounded-xl bg-[#0866ff] px-4 py-3 text-sm font-extrabold text-white">Create first advert</Link></div>}
function Quick({href,icon,title,text}:{href:string;icon:React.ReactNode;title:string;text:string}){return <Link href={href} className="fb-card block p-4 transition hover:bg-[#f7f8fa]"><div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[#e7f3ff] text-slate-900 [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</div><h3 className="font-black text-slate-900">{title}</h3></div><p className="mt-3 text-sm leading-6 text-slate-500">{text}</p></Link>}

function MobileNav({href,icon,label}:{href:string;icon:React.ReactNode;label:string}){return <Link href={href} className="flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[10px] font-semibold text-[#65676b]"><span className="[&>svg]:h-5 [&>svg]:w-5">{icon}</span><span>{label}</span></Link>}
