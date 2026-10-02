"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, BadgePercent, BarChart3, Bell, CalendarDays, CheckCircle2, ChevronRight, CircleDollarSign, Clock3, FileText, Globe2, Headphones, KeyRound, LayoutDashboard, Loader2, LogOut, Megaphone, Menu, Package, Send, Search, Settings, ShieldCheck, TrendingUp, Users, X } from "lucide-react";
import { api, clearSession, getSessionUser, SessionUser } from "@/lib/api";
import { useRealtimeTopics } from "@/app/components/RealtimeBridge";

type Campaign={id:number;advertiser_id:number;title:string;status:string;preferred_publish_at?:string|null;scheduled_publish_at?:string|null;created_at:string};
type Summary={advertisers:number;campaigns:number;awaiting_review:number;scheduled:number;published:number;paid_payments:number;revenue:number;currency:string;failed_publications:number};
type Notification={id:number;read_at?:string|null};

const label=(value:string)=>value.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());

export default function Dashboard(){
  const router=useRouter();
  const [user,setUser]=useState<SessionUser|null>(null);
  const [campaigns,setCampaigns]=useState<Campaign[]>([]);
  const [summary,setSummary]=useState<Summary|null>(null);
  const [notifications,setNotifications]=useState<Notification[]>([]);
  const [loading,setLoading]=useState(true);
  const [query,setQuery]=useState("");
  const [error,setError]=useState("");
  const [portalName,setPortalName]=useState("Meloli Airwaves");
  const [mobileNavOpen,setMobileNavOpen]=useState(false);

  async function refreshDashboard(silent=false){
    if(!silent)setLoading(true);
    try{
      const [c,s,n]=await Promise.all([api<Campaign[]>("/api/v1/campaigns",{},true),api<Summary>("/api/v1/admin/reports/summary",{},true),api<Notification[]>("/api/v1/notifications",{},true)]);
      setCampaigns(c);setSummary(s);setNotifications(n);setError("");
    }catch(e){if(!silent)setError(e instanceof Error?e.message:"Unable to load dashboard")}
    finally{if(!silent)setLoading(false)}
  }
  useEffect(()=>{const current=getSessionUser();if(!current||(current.role==="advertiser"&&!current.is_tenant_admin)){router.replace("/login");return;}setUser(current);refreshDashboard();if(current.is_tenant_admin)api<{name:string}>("/api/v1/tenant-admin/profile",{},true).then(p=>setPortalName(p.name)).catch(()=>undefined);},[router]);
  useRealtimeTopics(["campaign","payment","notification","tenant_billing","tenant"],()=>{refreshDashboard(true)});
  const unreadNotifications=notifications.filter(item=>!item.read_at).length;
  const filtered=useMemo(()=>campaigns.filter(c=>c.title.toLowerCase().includes(query.toLowerCase())).slice(0,8),[campaigns,query]);
  const schedule=useMemo(()=>campaigns.filter(c=>c.scheduled_publish_at&&["scheduled","published"].includes(c.status)).sort((a,b)=>new Date(a.scheduled_publish_at!).getTime()-new Date(b.scheduled_publish_at!).getTime()).slice(0,5),[campaigns]);
  const kpis=useMemo(()=>{
    const total=summary?.campaigns||0;
    const published=summary?.published||0;
    const awaiting=summary?.awaiting_review||0;
    const advertisers=summary?.advertisers||0;
    const failed=summary?.failed_publications||0;
    const approved=campaigns.filter(c=>["approved","scheduled","published"].includes(c.status)).length;
    const publishRate=total?Math.round((published/total)*100):0;
    const approvalRate=total?Math.round((approved/total)*100):0;
    const backlogRate=total?Math.round((awaiting/total)*100):0;
    const failureRate=(published+failed)?Math.round((failed/(published+failed))*100):0;
    const revenuePerAdvertiser=advertisers?Number(summary?.revenue||0)/advertisers:0;
    return {approved,publishRate,approvalRate,backlogRate,failureRate,revenuePerAdvertiser};
  },[campaigns,summary]);
  const statusData=useMemo(()=>{
    const total=Math.max(1,campaigns.length);
    const groups=[
      {label:"Awaiting review",value:campaigns.filter(c=>["submitted","in_review"].includes(c.status)).length,tone:"bg-amber-500"},
      {label:"Approved",value:campaigns.filter(c=>c.status==="approved").length,tone:"bg-[#0866ff]"},
      {label:"Scheduled",value:campaigns.filter(c=>c.status==="scheduled").length,tone:"bg-violet-500"},
      {label:"Published",value:campaigns.filter(c=>c.status==="published").length,tone:"bg-emerald-500"},
    ];
    return groups.map(row=>({...row,percent:Math.round((row.value/total)*100)}));
  },[campaigns]);
  const recentActivity=useMemo(()=>[...campaigns].sort((a,b)=>new Date(b.created_at).getTime()-new Date(a.created_at).getTime()).slice(0,6),[campaigns]);
  function logout(){clearSession();router.push("/login")}

  return <main className="fb-page">
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-72 flex-col border-r border-slate-200 bg-white text-slate-900 lg:flex"><div className="flex h-16 items-center gap-3 border-b border-slate-200 px-4"><div className="grid h-10 w-10 place-items-center rounded-full bg-[#0866ff] text-white"><Megaphone size={19}/></div><div className="min-w-0"><div className="truncate text-[15px] font-bold text-slate-900">{portalName}</div><div className="text-xs text-[#65676b]">Admin Console</div></div></div><nav className="flex-1 space-y-1 overflow-y-auto p-2 text-[15px] font-semibold"><Nav icon={<LayoutDashboard/>} label="Overview" active href="/dashboard"/><Nav icon={<Megaphone/>} label="Campaigns" href="/dashboard/campaigns"/><Nav icon={<CheckCircle2/>} label="Approvals" href="/dashboard/campaigns"/><Nav icon={<CalendarDays/>} label="Publishing calendar" href="/dashboard/calendar"/><Nav icon={<Package/>} label="Packages & pricing" href="/dashboard/packages"/>{user?.role==="super_admin"&&<Nav icon={<BadgePercent/>} label="Commercial growth" href="/dashboard/commercial"/>}{user?.role==="super_admin"&&<Nav icon={<TrendingUp/>} label="Growth & referrals" href="/dashboard/growth"/>}{user?.role==="super_admin"&&<Nav icon={<KeyRound/>} label="Corporate API" href="/dashboard/corporate-api"/>}{user?.role==="super_admin"&&<><Nav icon={<Globe2/>} label="Page portals" href="/dashboard/tenants"/><Nav icon={<CircleDollarSign/>} label="Tenant billing" href="/dashboard/tenant-billing"/></>}<Nav icon={<Users/>} label="Advertisers" href="/dashboard/campaigns"/><Nav icon={<CircleDollarSign/>} label="Payments" href="/dashboard/payments"/>{user?.role==="super_admin"&&<Nav icon={<FileText/>} label="Refund review" href="/dashboard/refunds"/>}<Nav icon={<FileText/>} label="Reports" href="/dashboard/reports"/><Nav icon={<Headphones/>} label="Advertiser support" href="/dashboard/support"/>{user?.role==="super_admin"&&<Nav icon={<Bell/>} label="Notification delivery" href="/dashboard/notification-delivery"/>}<Nav icon={<ShieldCheck/>} label="Staff security" href="/dashboard/security"/>{user?.role==="super_admin"&&<><Nav icon={<Activity/>} label="Automation health" href="/dashboard/automation"/><Nav icon={<FileText/>} label="Audit & activity" href="/dashboard/audit"/></>}{user?.role==="super_admin"&&<Nav icon={<Send/>} label="Notifications" href="/dashboard/communications"/>}{user?.is_tenant_admin&&<><Nav icon={<Users/>} label="Page team & onboarding" href="/tenant-admin/team"/><Nav icon={<CircleDollarSign/>} label="Page subscription billing" href="/tenant-admin/billing"/><Nav icon={<Globe2/>} label="Page portal settings" href="/tenant-admin/settings"/></>}{!user?.is_tenant_admin&&<Nav icon={<Settings/>} label="Settings" href="/dashboard/settings"/>}</nav><button onClick={logout} className="m-3 flex items-center gap-3 rounded-lg p-2.5 text-left hover:bg-[#f2f2f2]"><div className="fb-avatar h-10 w-10 text-sm">{user?.full_name?.slice(0,2).toUpperCase()||"MA"}</div><div className="min-w-0 flex-1"><p className="truncate text-sm font-bold text-slate-900">{user?.full_name||"Admin"}</p><p className="truncate text-xs text-[#65676b]">{user?.role?.replaceAll("_"," ")||"staff"}</p></div><LogOut size={17} className="text-[#65676b]"/></button></aside>

    {mobileNavOpen&&<><button aria-label="Close navigation overlay" onClick={()=>setMobileNavOpen(false)} className="fixed inset-0 z-50 bg-black/40 lg:hidden"/><aside className="fixed inset-y-0 left-0 z-[60] flex w-[86vw] max-w-[340px] flex-col bg-white shadow-2xl lg:hidden"><div className="flex h-16 items-center gap-3 border-b border-slate-200 px-4"><div className="grid h-10 w-10 place-items-center rounded-full bg-[#0866ff] text-white"><Megaphone size={19}/></div><div className="min-w-0 flex-1"><p className="truncate font-bold text-slate-900">{portalName}</p><p className="text-xs text-[#65676b]">Admin Console</p></div><button onClick={()=>setMobileNavOpen(false)} className="fb-icon-button"><X size={18}/></button></div><nav onClick={()=>setMobileNavOpen(false)} className="flex-1 space-y-1 overflow-y-auto p-2 text-[15px] font-semibold"><Nav icon={<LayoutDashboard/>} label="Overview" active href="/dashboard"/><Nav icon={<Megaphone/>} label="Campaigns" href="/dashboard/campaigns"/><Nav icon={<CalendarDays/>} label="Publishing calendar" href="/dashboard/calendar"/><Nav icon={<Package/>} label="Packages & pricing" href="/dashboard/packages"/>{user?.role==="super_admin"&&<Nav icon={<Globe2/>} label="Page portals" href="/dashboard/tenants"/>}{user?.role==="super_admin"&&<Nav icon={<CircleDollarSign/>} label="Tenant billing" href="/dashboard/tenant-billing"/>}{user?.role==="super_admin"&&<Nav icon={<Activity/>} label="Automation" href="/dashboard/automation"/>}<Nav icon={<CircleDollarSign/>} label="Payments" href="/dashboard/payments"/><Nav icon={<FileText/>} label="Reports" href="/dashboard/reports"/><Nav icon={<Headphones/>} label="Support" href="/dashboard/support"/>{user?.is_tenant_admin&&<Nav icon={<Users/>} label="Team & onboarding" href="/tenant-admin/team"/>}{user?.is_tenant_admin&&<Nav icon={<Settings/>} label="Portal settings" href="/tenant-admin/settings"/>}</nav><button onClick={logout} className="m-3 flex items-center gap-3 rounded-lg p-2.5 text-left hover:bg-[#f2f2f2]"><div className="fb-avatar h-10 w-10 text-sm">{user?.full_name?.slice(0,2).toUpperCase()||"MA"}</div><div className="min-w-0 flex-1"><p className="truncate text-sm font-bold">{user?.full_name||"Admin"}</p><p className="truncate text-xs text-[#65676b]">Sign out</p></div><LogOut size={17}/></button></aside></>}

    <div className="lg:pl-72"><header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-slate-200 bg-white px-3 shadow-sm sm:px-4 lg:px-6"><button onClick={()=>setMobileNavOpen(true)} className="fb-icon-button lg:hidden" aria-label="Open navigation"><Menu size={20}/></button><div className="min-w-0 flex-1"><h1 className="truncate text-lg font-bold text-slate-900">Advertising Operations</h1><p className="hidden text-xs text-slate-500 sm:block">Live {portalName} advertising workflow</p></div><div className="hidden h-10 w-80 items-center gap-3 rounded-full bg-[#f0f2f5] px-4 md:flex"><Search size={17} className="text-slate-400"/><input value={query} onChange={e=>setQuery(e.target.value)} className="w-full bg-transparent text-sm outline-none" placeholder="Search campaigns..."/></div><Link href="/dashboard/notifications" className="fb-icon-button relative"><Bell size={18}/>{unreadNotifications>0?<span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-[#e41e3f] px-1.5 py-0.5 text-center text-[10px] font-bold leading-4 text-white">{unreadNotifications>99?"99+":unreadNotifications}</span>:null}</Link></header>

      <div className="mx-auto max-w-[1500px] p-3 pb-24 sm:p-4 sm:pb-24 lg:p-6 lg:pb-6">
        {error&&<div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}

        <section className="mb-4 flex flex-col gap-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-[#0866ff]">{portalName}</p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Advertising operations</h2>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-[#65676b]">Live commercial, editorial and Facebook publishing performance in one workspace.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link href="/dashboard/campaigns" className="fb-primary inline-flex h-10 items-center gap-2 px-4 text-sm"><CheckCircle2 size={16}/> Review campaigns</Link>
            <Link href="/dashboard/reports" className="fb-secondary inline-flex h-10 items-center gap-2 px-4 text-sm"><BarChart3 size={16}/> Analytics</Link>
          </div>
        </section>

        {loading?<div className="grid min-h-56 place-items-center"><Loader2 className="animate-spin text-[#0866ff]"/></div>:<>
          <section className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
            <CompactMetric label="Revenue" value={`${summary?.currency||"LSL"} ${Number(summary?.revenue||0).toLocaleString()}`} detail={`${summary?.paid_payments||0} payments`}/>
            <CompactMetric label="Advertisers" value={String(summary?.advertisers||0)} detail="Active customer base"/>
            <CompactMetric label="Campaigns" value={String(summary?.campaigns||0)} detail="All submissions"/>
            <CompactMetric label="Awaiting review" value={String(summary?.awaiting_review||0)} detail={`${kpis.backlogRate}% backlog`}/>
            <CompactMetric label="Published" value={String(summary?.published||0)} detail={`${kpis.publishRate}% publish rate`}/>
            <CompactMetric label="Scheduled" value={String(summary?.scheduled||0)} detail="Upcoming posts"/>
          </section>

          <section className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,.55fr)]">
            <div className="space-y-4">
              <div className="fb-card overflow-hidden">
                <div className="flex flex-col gap-3 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div><h3 className="text-base font-bold text-slate-900">Campaign operations feed</h3><p className="mt-0.5 text-sm text-[#65676b]">Latest submissions, approvals and publishing states.</p></div>
                  <Link href="/dashboard/campaigns" className="text-sm font-semibold text-[#0866ff]">See all campaigns</Link>
                </div>
                {filtered.length===0?<div className="p-8 text-center text-sm text-[#65676b]">No campaigns match your search.</div>:<div className="divide-y divide-slate-200">{filtered.map(c=><Link href="/dashboard/campaigns" key={c.id} className="flex items-center gap-3 p-3 transition hover:bg-[#f7f8fa] sm:p-4">
                  <div className="fb-avatar h-10 w-10 shrink-0 bg-[#e7f3ff] text-[#0866ff]"><Megaphone size={17}/></div>
                  <div className="min-w-0 flex-1"><p className="truncate text-[15px] font-semibold text-slate-900">{c.title}</p><p className="mt-0.5 truncate text-xs text-[#65676b]">Advertiser #{c.advertiser_id} · Campaign #{c.id} · {new Date(c.created_at).toLocaleDateString()}</p></div>
                  <Status value={c.status}/>
                  <ChevronRight size={17} className="hidden shrink-0 text-slate-300 sm:block"/>
                </Link>)}</div>}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="fb-card p-4">
                  <div className="flex items-center justify-between"><div><h3 className="font-bold text-slate-900">Workflow distribution</h3><p className="mt-0.5 text-xs text-[#65676b]">Where current campaigns sit.</p></div><BarChart3 size={19} className="text-[#0866ff]"/></div>
                  <div className="mt-5 space-y-4">{statusData.map(row=><div key={row.label}><div className="mb-1.5 flex items-center justify-between text-xs"><span className="font-semibold text-slate-700">{row.label}</span><span className="text-[#65676b]">{row.value} · {row.percent}%</span></div><div className="h-2 overflow-hidden rounded-full bg-[#e4e6eb]"><div className={`h-full rounded-full ${row.tone}`} style={{width:`${Math.max(row.percent,row.value?4:0)}%`}}/></div></div>)}</div>
                </div>
                <div className="fb-card p-4">
                  <div className="flex items-center justify-between"><div><h3 className="font-bold text-slate-900">Performance health</h3><p className="mt-0.5 text-xs text-[#65676b]">Operational rates from live data.</p></div><TrendingUp size={19} className="text-[#0866ff]"/></div>
                  <div className="mt-4 grid grid-cols-2 gap-2">
                    <RateTile label="Approval rate" value={kpis.approvalRate} good/>
                    <RateTile label="Publish rate" value={kpis.publishRate} good/>
                    <RateTile label="Backlog rate" value={kpis.backlogRate}/>
                    <RateTile label="Failure rate" value={kpis.failureRate} danger/>
                  </div>
                </div>
              </div>
            </div>

            <aside className="space-y-4">
              <div className="fb-card p-4">
                <div className="flex items-center justify-between"><div><h3 className="font-bold text-slate-900">Publishing schedule</h3><p className="mt-0.5 text-xs text-[#65676b]">Next approved posts.</p></div><CalendarDays size={19} className="text-[#0866ff]"/></div>
                <div className="mt-4 space-y-4">{schedule.length===0?<p className="py-4 text-sm text-[#65676b]">Nothing scheduled yet.</p>:schedule.map(c=><Schedule key={c.id} date={c.scheduled_publish_at!} title={c.title} state={label(c.status)}/>)}</div>
                <Link href="/dashboard/calendar" className="mt-4 block rounded-lg bg-[#e7f3ff] px-3 py-2.5 text-center text-sm font-semibold text-[#0866ff]">Open publishing calendar</Link>
              </div>

              <div className="fb-card p-4">
                <div className="flex items-center justify-between"><div><h3 className="font-bold text-slate-900">Recent activity</h3><p className="mt-0.5 text-xs text-[#65676b]">Newest campaign activity.</p></div><Clock3 size={19} className="text-[#0866ff]"/></div>
                <div className="mt-3 divide-y divide-slate-100">{recentActivity.map(c=><div key={c.id} className="flex gap-3 py-3"><div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#0866ff]"/><div className="min-w-0"><p className="truncate text-sm font-semibold text-slate-800">{c.title}</p><p className="mt-0.5 text-xs text-[#65676b]">{label(c.status)} · {new Date(c.created_at).toLocaleDateString()}</p></div></div>)}</div>
              </div>

              <div className={`rounded-xl border p-4 ${(summary?.failed_publications||0)>0?"border-rose-200 bg-rose-50":"border-emerald-200 bg-emerald-50"}`}>
                <div className="flex items-start gap-3"><div className={`grid h-9 w-9 shrink-0 place-items-center rounded-full ${(summary?.failed_publications||0)>0?"bg-rose-100 text-rose-700":"bg-emerald-100 text-emerald-700"}`}><Bell size={17}/></div><div><p className="font-bold text-slate-900">Publishing health</p><p className="mt-1 text-sm leading-5 text-[#65676b]">{summary?.failed_publications||0} failed attempts · {kpis.failureRate}% failure rate.</p><Link href="/dashboard/reports" className="mt-2 inline-block text-sm font-semibold text-[#0866ff]">Inspect publishing analytics</Link></div></div>
              </div>
            </aside>
          </section>
        </>}

        <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)] shadow-[0_-1px_8px_rgba(0,0,0,.08)] lg:hidden">
          <MobileAdminNav href="/dashboard" icon={<LayoutDashboard/>} label="Home" active/>
          <MobileAdminNav href="/dashboard/campaigns" icon={<Megaphone/>} label="Campaigns"/>
          <MobileAdminNav href="/dashboard/calendar" icon={<CalendarDays/>} label="Calendar"/>
          <MobileAdminNav href="/dashboard/reports" icon={<BarChart3/>} label="Analytics"/>
          <button onClick={()=>setMobileNavOpen(true)} className="flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[10px] font-semibold text-[#65676b]"><Menu size={20}/><span>Menu</span></button>
        </nav>
      </div></div>
  </main>;
}

function Nav({icon,label,active,href}:{icon:React.ReactNode;label:string;active?:boolean;href:string}){return <Link href={href} className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left ${active?"bg-[#e7f3ff] text-[#0866ff]":"text-slate-700 hover:bg-[#f2f2f2]"}`}><span className="[&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span><span className="flex-1">{label}</span></Link>}
function CompactMetric({label,value,detail}:{label:string;value:string;detail:string}){return <div className="fb-card min-w-0 p-3 sm:p-4"><p className="truncate text-xs font-semibold text-[#65676b]">{label}</p><p className="mt-1 truncate text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">{value}</p><p className="mt-1 truncate text-[11px] text-[#8a8d91]">{detail}</p></div>}
function RateTile({label,value,good,danger}:{label:string;value:number;good?:boolean;danger?:boolean}){const tone=danger&&value>0?"text-rose-700 bg-rose-50":good?"text-emerald-700 bg-emerald-50":"text-[#0866ff] bg-[#e7f3ff]";return <div className={`rounded-lg p-3 ${tone}`}><p className="text-[11px] font-semibold opacity-80">{label}</p><p className="mt-1 text-2xl font-bold">{value}%</p></div>}
function MobileAdminNav({href,icon,label,active}:{href:string;icon:React.ReactNode;label:string;active?:boolean}){return <Link href={href} className={`flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[10px] font-semibold ${active?"text-[#0866ff]":"text-[#65676b]"}`}><span className="[&>svg]:h-5 [&>svg]:w-5">{icon}</span><span>{label}</span></Link>}
function Status({value}:{value:string}){const cls=value==="published"?"bg-emerald-50 text-emerald-700":value==="approved"||value==="scheduled"?"bg-blue-50 text-blue-700":value==="rejected"||value==="changes_requested"?"bg-rose-50 text-rose-700":"bg-amber-50 text-amber-700";return <span className={`w-fit rounded-full px-3 py-1.5 text-xs font-extrabold ${cls}`}>{label(value)}</span>}
function Schedule({date,title,state}:{date:string;title:string;state:string}){const d=new Date(date);return <div className="flex gap-4"><div className="w-14 pt-0.5 text-xs font-bold text-slate-900">{d.toLocaleDateString(undefined,{month:"short",day:"numeric"})}<br/><span className="text-slate-400">{d.toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit"})}</span></div><div className="relative flex-1 border-l border-slate-200 pl-4 before:absolute before:-left-[5px] before:top-1 before:h-2.5 before:w-2.5 before:rounded-full before:bg-[#0866ff]"><p className="text-sm font-extrabold text-slate-800">{title}</p><p className="mt-1 text-xs text-slate-400">{state}</p></div></div>}
