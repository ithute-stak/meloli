"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, AlertTriangle, ArrowLeft, CheckCircle2, Loader2, RefreshCw, RotateCcw, Webhook } from "lucide-react";
import { api, getSessionUser, SessionUser } from "@/lib/api";
import { useRealtimeTopics } from "@/app/components/RealtimeBridge";

type WebhookEvent={id:number;tenant_id?:number|null;page_id?:string|null;object_type:string;status:string;attempts:number;last_error?:string|null;received_at:string;processed_at?:string|null};
type MetaHealth={connected:boolean;page_name?:string|null;page_id?:string|null;health_status?:string|null;health_detail?:string|null;health_checked_at?:string|null};
type Domain={id:number;hostname:string;status:string;health_status?:string|null;health_detail?:string|null};
type Profile={name:string;domains:Domain[]};
type PlatformHealth={backup:{status?:string|null;detail?:string|null;checked_at?:string|null}};

export default function IntegrationsHealthPage(){
  const router=useRouter();
  const [user,setUser]=useState<SessionUser|null>(null);
  const [events,setEvents]=useState<WebhookEvent[]>([]);
  const [meta,setMeta]=useState<MetaHealth|null>(null);
  const [profile,setProfile]=useState<Profile|null>(null);
  const [platformHealth,setPlatformHealth]=useState<PlatformHealth|null>(null);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState<number|null>(null);
  const [error,setError]=useState("");

  async function load(silent=false){
    if(!silent)setLoading(true);
    try{
      const current=getSessionUser();
      const requests:Promise<unknown>[]=[api<WebhookEvent[]>("/api/v1/admin/meta/webhook-events",{},true)];
      if(current?.is_tenant_admin){
        requests.push(api<MetaHealth>("/api/v1/tenant-admin/meta",{},true));
        requests.push(api<Profile>("/api/v1/tenant-admin/profile",{},true));
      }else if(current?.role==="super_admin"){
        requests.push(api<PlatformHealth>("/api/v1/admin/platform-health",{},true));
      }
      const result=await Promise.all(requests);
      setEvents(result[0] as WebhookEvent[]);
      if(current?.is_tenant_admin){setMeta(result[1] as MetaHealth);setProfile(result[2] as Profile)}
      else if(current?.role==="super_admin"){setPlatformHealth(result[1] as PlatformHealth)}
      setError("");
    }catch(e){setError(e instanceof Error?e.message:"Unable to load integration health")}
    finally{if(!silent)setLoading(false)}
  }

  useEffect(()=>{
    const current=getSessionUser();
    if(!current||(current.role==="advertiser"&&!current.is_tenant_admin)){router.replace("/login");return}
    setUser(current);load();
  },[router]);
  useRealtimeTopics(["meta","integration"],()=>load(true));

  const stats=useMemo(()=>({
    pending:events.filter(e=>e.status==="pending").length,
    failed:events.filter(e=>e.status==="failed").length,
    dead:events.filter(e=>e.status==="dead_letter").length,
    processed:events.filter(e=>e.status==="processed").length,
  }),[events]);

  async function retry(id:number){
    setBusy(id);setError("");
    try{await api("/api/v1/admin/meta/webhook-events/"+id+"/retry",{method:"POST"},true);await load(true)}
    catch(e){setError(e instanceof Error?e.message:"Unable to requeue webhook event")}
    finally{setBusy(null)}
  }

  return <main className="fb-page">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white shadow-sm">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-3 sm:px-4 lg:px-6">
        <Link href="/dashboard" className="fb-icon-button"><ArrowLeft size={18}/></Link>
        <div className="min-w-0 flex-1"><h1 className="text-[17px] font-bold text-slate-900">Integration health</h1><p className="hidden text-xs text-[#65676b] sm:block">Meta connectivity, domain routing and webhook delivery health.</p></div>
        <button onClick={()=>load()} className="fb-icon-button" aria-label="Refresh integration health"><RefreshCw size={17}/></button>
      </div>
    </header>

    <div className="mx-auto max-w-[1400px] p-3 sm:p-4 lg:p-6">
      {error&&<div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}
      {loading?<div className="grid min-h-64 place-items-center"><Loader2 className="animate-spin text-[#0866ff]"/></div>:<>
        {user?.role==="super_admin"&&<section className="mb-4"><HealthCard title="Backup health" status={platformHealth?.backup.status||"unknown"} detail={platformHealth?.backup.detail||"Backup health check has not run yet."}/></section>}
        {user?.is_tenant_admin&&<section className="mb-4 grid gap-3 md:grid-cols-2">
          <HealthCard title="Facebook / Meta connection" status={meta?.health_status|| (meta?.connected?"configured":"unknown")} detail={meta?.health_detail|| (meta?.page_name?"Connected to "+meta.page_name:"Health check has not run yet.")}/>
          <div className="fb-card p-4"><div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-full bg-[#e7f3ff] text-[#0866ff]"><Activity size={18}/></div><div><h2 className="font-bold text-slate-900">Custom domains</h2><p className="text-xs text-[#65676b]">{profile?.domains?.length||0} configured</p></div></div><div className="mt-4 space-y-2">{!profile?.domains?.length?<p className="text-sm text-[#65676b]">No custom domains configured.</p>:profile.domains.map(domain=><div key={domain.id} className="flex items-center justify-between gap-3 rounded-lg bg-[#f7f8fa] px-3 py-2.5"><div className="min-w-0"><p className="truncate text-sm font-semibold text-slate-800">{domain.hostname}</p><p className="truncate text-xs text-[#65676b]">{domain.health_detail||"Health check pending"}</p></div><HealthPill value={domain.health_status||domain.status}/></div>)}</div></div>
        </section>}

        <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Kpi label="Processed" value={stats.processed} good/>
          <Kpi label="Pending" value={stats.pending}/>
          <Kpi label="Retrying" value={stats.failed} warning/>
          <Kpi label="Dead letter" value={stats.dead} bad/>
        </section>

        <section className="mt-4 fb-card overflow-hidden">
          <div className="flex flex-col gap-2 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between"><div><h2 className="font-bold text-slate-900">Meta webhook inbox</h2><p className="mt-0.5 text-sm text-[#65676b]">Durable Facebook event delivery with deduplication and retry tracking.</p></div><span className="text-xs font-semibold text-[#65676b]">{events.length} recent events</span></div>
          {events.length===0?<div className="p-8 text-center text-sm text-[#65676b]">No Meta webhook events received yet.</div>:<div className="divide-y divide-slate-100">{events.map(event=><article key={event.id} className="p-4"><div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_120px_100px_170px_auto] lg:items-center"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><Webhook size={16} className="text-[#0866ff]"/><p className="font-semibold text-slate-900">Event #{event.id}</p><HealthPill value={event.status}/></div><p className="mt-1 truncate text-xs text-[#65676b]">{event.page_id||"Unknown Page"}{event.last_error?" · "+event.last_error:""}</p></div><Cell label="Tenant" value={event.tenant_id?String(event.tenant_id):"—"}/><Cell label="Attempts" value={String(event.attempts)}/><Cell label="Received" value={new Date(event.received_at).toLocaleString()}/><div>{["failed","dead_letter"].includes(event.status)&&<button disabled={busy===event.id} onClick={()=>retry(event.id)} className="fb-secondary inline-flex h-9 items-center gap-2 px-3 text-xs disabled:opacity-50">{busy===event.id?<Loader2 size={14} className="animate-spin"/>:<RotateCcw size={14}/>} Retry</button>}</div></div></article>)}</div>}
        </section>
      </>}
    </div>
  </main>;
}

function HealthCard({title,status,detail}:{title:string;status:string;detail:string}){const healthy=status==="healthy";const bad=status==="unhealthy";return <div className="fb-card p-4"><div className="flex items-start gap-3"><div className={"grid h-10 w-10 shrink-0 place-items-center rounded-full "+(healthy?"bg-emerald-50 text-emerald-700":bad?"bg-rose-50 text-rose-700":"bg-[#e7f3ff] text-[#0866ff]")}>{healthy?<CheckCircle2 size={18}/>:bad?<AlertTriangle size={18}/>:<Activity size={18}/>}</div><div><h2 className="font-bold text-slate-900">{title}</h2><p className="mt-1 text-sm leading-5 text-[#65676b]">{detail}</p><div className="mt-2"><HealthPill value={status}/></div></div></div></div>}
function HealthPill({value}:{value:string}){const cls=["healthy","processed","verified"].includes(value)?"bg-emerald-50 text-emerald-700":["unhealthy","dead_letter"].includes(value)?"bg-rose-50 text-rose-700":["failed","pending"].includes(value)?"bg-amber-50 text-amber-700":"bg-slate-100 text-slate-600";return <span className={"rounded-full px-2.5 py-1 text-[10px] font-semibold "+cls}>{value.replaceAll("_"," ")}</span>}
function Kpi({label,value,good,warning,bad}:{label:string;value:number;good?:boolean;warning?:boolean;bad?:boolean}){const cls=bad?"text-rose-700":warning?"text-amber-700":good?"text-emerald-700":"text-[#0866ff]";return <div className="fb-card p-3 sm:p-4"><p className={"text-2xl font-bold "+cls}>{value}</p><p className="mt-1 text-xs font-semibold text-[#65676b]">{label}</p></div>}
function Cell({label,value}:{label:string;value:string}){return <div><p className="text-[10px] font-semibold text-[#8a8d91]">{label}</p><p className="mt-1 text-sm font-semibold text-slate-800">{value}</p></div>}
