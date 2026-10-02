"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, CircleDollarSign, ExternalLink, Globe2, Share2, Loader2, RefreshCw, ShieldCheck, Users } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";

type Domain={id:number;hostname:string;status:string;verified_at?:string|null};
type Plan={id:number;code:string;name:string;monthly_price:number;annual_price:number;currency:string;max_staff:number;max_campaigns_monthly:number;custom_domains:boolean;competition_certification:boolean;active:boolean};
type Subscription={id:number;status:string;billing_period:string;price_amount:number;currency:string;usable:boolean;current_period_end:string;plan:{id:number;code:string;name:string;max_staff:number;max_campaigns_monthly:number;custom_domains:boolean;competition_certification:boolean}};
type Tenant={id:number;name:string;slug:string;facebook_page_name?:string|null;facebook_page_id?:string|null;generated_url:string;active:boolean;owner?:{id:number;name:string;email:string}|null;users:number;campaigns:number;domains:Domain[];subscription?:Subscription|null;onboarding_percent:number};
type Summary={tenants:number;active_tenants:number;trialing_subscriptions:number;active_subscriptions:number;subscription_mrr:number;subscription_acv:number;currency:string;connected_meta_pages:number;verified_domains:number};
type Assignment={planId:number;billing:"monthly"|"annual"};

export default function TenantsPage(){
 const router=useRouter();
 const [rows,setRows]=useState<Tenant[]>([]);
 const [plans,setPlans]=useState<Plan[]>([]);
 const [summary,setSummary]=useState<Summary|null>(null);
 const [assignments,setAssignments]=useState<Record<number,Assignment>>({});
 const [loading,setLoading]=useState(true);
 const [busy,setBusy]=useState("");
 const [error,setError]=useState("");
 const [message,setMessage]=useState("");

 async function load(){
  setLoading(true);setError("");
  try{
   const [tenantRows,planRows,stats]=await Promise.all([
    api<Tenant[]>("/api/v1/admin/tenants",{},true),
    api<Plan[]>("/api/v1/admin/tenant-plans",{},true),
    api<Summary>("/api/v1/admin/platform/summary",{},true),
   ]);
   setRows(tenantRows);setPlans(planRows);setSummary(stats);
   setAssignments(current=>{
    const next={...current};
    for(const tenant of tenantRows){
     if(!next[tenant.id]){
      next[tenant.id]={
       planId:tenant.subscription?.plan.id||planRows[0]?.id||0,
       billing:(tenant.subscription?.billing_period==="annual"?"annual":"monthly"),
      };
     }
    }
    return next;
   });
  }catch(e){setError(e instanceof Error?e.message:"Unable to load Page portals")}finally{setLoading(false)}
 }
 useEffect(()=>{const u=getSessionUser();if(!u||u.role!=="super_admin"){router.replace("/dashboard");return;}load();},[router]);

 const metrics=useMemo(()=>[
  {label:"Page tenants",value:String(summary?.tenants||0),hint:`${summary?.active_tenants||0} active`,icon:<Globe2/>},
  {label:"Subscription MRR",value:`${summary?.currency||"LSL"} ${Number(summary?.subscription_mrr||0).toLocaleString()}`,hint:"Active tenant subscriptions",icon:<CircleDollarSign/>},
  {label:"Active subscriptions",value:String(summary?.active_subscriptions||0),hint:`${summary?.trialing_subscriptions||0} currently trialing`,icon:<ShieldCheck/>},
  {label:"Connected Meta Pages",value:String(summary?.connected_meta_pages||0),hint:`${summary?.verified_domains||0} verified custom domains`,icon:<Share2/>},
 ],[summary]);

 async function toggle(id:number,active:boolean){setBusy("tenant-"+id);setError("");setMessage("");try{await api("/api/v1/admin/tenants/"+id+"/state",{method:"PATCH",body:JSON.stringify({active:!active})},true);setMessage(active?"Portal disabled.":"Portal enabled.");await load();}catch(e){setError(e instanceof Error?e.message:"Unable to update portal")}finally{setBusy("")}}
 async function verifyDomain(id:number){setBusy("domain-"+id);setError("");setMessage("");try{await api("/api/v1/admin/tenant-domains/"+id+"/verify",{method:"POST"},true);setMessage("Custom domain verified.");await load();}catch(e){setError(e instanceof Error?e.message:"Unable to verify domain")}finally{setBusy("")}}
 async function applyPlan(tenantId:number){
  const assignment=assignments[tenantId]; if(!assignment?.planId)return;
  setBusy("plan-"+tenantId);setError("");setMessage("");
  try{
   await api("/api/v1/admin/tenants/"+tenantId+"/subscription",{method:"PUT",body:JSON.stringify({plan_id:assignment.planId,billing_period:assignment.billing,status:"active"})},true);
   setMessage("Tenant subscription updated.");await load();
  }catch(e){setError(e instanceof Error?e.message:"Unable to update tenant subscription")}finally{setBusy("")}
 }

 return <main className="min-h-screen bg-[#f0f2f5] text-slate-900">
  <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex h-20 max-w-[1450px] items-center gap-4 px-4 sm:px-6"><Link href="/dashboard" className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200"><ArrowLeft size={18}/></Link><div className="flex-1"><h1 className="font-bold text-slate-900">Facebook Page SaaS</h1><p className="text-xs text-slate-500">Tenant subscriptions, onboarding, domains and Page-level platform operations.</p></div><button onClick={load} className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200"><RefreshCw size={16}/></button></div></header>
  <div className="mx-auto max-w-[1450px] p-4 sm:p-6 lg:p-8">
   {error&&<div className="mb-5 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}
   {message&&<div className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-700">{message}</div>}
   {loading?<div className="grid min-h-64 place-items-center"><Loader2 className="animate-spin text-[#0866ff]"/></div>:<>
    <section className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{metrics.map(m=><Metric key={m.label} {...m}/>)}</section>
    <section className="mb-6 rounded-xl bg-[#070a45] p-6 text-white sm:p-8"><p className="text-xs font-bold tracking-normal text-white/45">Platform SaaS controls</p><h2 className="mt-2 text-2xl font-bold">Every Facebook Page is an independent tenant.</h2><p className="mt-3 max-w-3xl text-sm leading-6 text-white/60">Plans control team capacity, monthly campaign volume, custom domains and competition certification. Subscription revenue below is Page-platform revenue, separate from advertiser campaign payments.</p></section>
    <div className="space-y-4">{rows.map(t=>{
      const selection=assignments[t.id]||{planId:plans[0]?.id||0,billing:"monthly" as const};
      return <section key={t.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
       <div className="grid gap-5 p-5 sm:p-6 xl:grid-cols-[1.2fr_.7fr_.7fr_.8fr_auto] xl:items-center">
        <div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-bold text-slate-900">{t.name}</h2><span className={"rounded-full px-2.5 py-1 text-[10px] font-semibold "+(t.active?"bg-emerald-50 text-emerald-700":"bg-slate-100 text-slate-500")}>{t.active?"Active":"Disabled"}</span>{t.subscription&&<span className={"rounded-full px-2.5 py-1 text-[10px] font-semibold "+(t.subscription.status==="active"?"bg-blue-50 text-blue-700":"bg-amber-50 text-amber-700")}>{t.subscription.plan.name} · {t.subscription.status}</span>}</div><p className="mt-1 text-xs text-slate-400">/{t.slug}{t.facebook_page_id?" · Facebook Page "+t.facebook_page_id:""}</p><a href={t.generated_url} target="_blank" className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-[#0866ff]">Open generated portal <ExternalLink size={14}/></a></div>
        <div><p className="text-[10px] font-bold tracking-normal text-slate-400">Owner</p><p className="mt-1 text-sm font-semibold text-slate-700">{t.owner?.name||"No owner"}</p><p className="mt-1 truncate text-xs text-slate-400">{t.owner?.email||"—"}</p></div>
        <div className="grid grid-cols-2 gap-3"><Stat icon={<Users/>} label="Users" value={t.users}/><Stat icon={<Globe2/>} label="Campaigns" value={t.campaigns}/></div>
        <div><div className="flex items-center justify-between text-xs font-bold"><span className="text-slate-500">Onboarding</span><span className="text-slate-900">{t.onboarding_percent}%</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-[#0866ff]" style={{width:`${t.onboarding_percent}%`}}/></div>{t.subscription&&<p className="mt-2 text-[11px] text-slate-400">{t.subscription.plan.max_staff} staff · {t.subscription.plan.max_campaigns_monthly} campaigns/month</p>}</div>
        <button disabled={busy==="tenant-"+t.id} onClick={()=>toggle(t.id,t.active)} className={"rounded-xl px-4 py-2.5 text-xs font-semibold disabled:opacity-50 "+(t.active?"border border-rose-200 text-rose-700":"bg-[#070a45] text-white")}>{t.active?"Disable portal":"Enable portal"}</button>
       </div>
       <div className="grid gap-4 border-t border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-6 lg:grid-cols-[1fr_auto] lg:items-end">
        <div><p className="mb-2 text-[10px] font-bold tracking-normal text-slate-400">Tenant subscription</p><div className="grid gap-2 sm:grid-cols-[minmax(180px,1fr)_160px_auto]"><select value={selection.planId} onChange={e=>setAssignments(x=>({...x,[t.id]:{...selection,planId:Number(e.target.value)}}))} className="h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold text-slate-900">{plans.filter(p=>p.active).map(p=><option key={p.id} value={p.id}>{p.name} · {p.currency} {p.monthly_price}/mo</option>)}</select><select value={selection.billing} onChange={e=>setAssignments(x=>({...x,[t.id]:{...selection,billing:e.target.value as "monthly"|"annual"}}))} className="h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm font-bold"><option value="monthly">Monthly</option><option value="annual">Annual</option></select><button onClick={()=>applyPlan(t.id)} disabled={busy==="plan-"+t.id} className="h-11 rounded-xl bg-[#070a45] px-4 text-xs font-semibold text-white disabled:opacity-50">{busy==="plan-"+t.id?"Saving...":"Apply plan"}</button></div></div>
        <div className="text-right"><p className="text-[10px] font-bold tracking-normal text-slate-400">Current price</p><p className="mt-1 font-bold text-slate-900">{t.subscription?`${t.subscription.currency} ${Number(t.subscription.price_amount).toLocaleString()} / ${t.subscription.billing_period==="annual"?"year":"month"}`:"No subscription"}</p></div>
       </div>
       {t.domains.length>0&&<div className="border-t border-slate-100 px-5 py-4 sm:px-6"><p className="mb-3 text-[10px] font-bold tracking-normal text-slate-400">Custom domains</p><div className="flex flex-wrap gap-2">{t.domains.map(d=><div key={d.id} className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs"><span className="font-bold text-slate-700">{d.hostname}</span><span className={d.status==="verified"?"text-emerald-700":"text-amber-700"}>{d.status}</span>{d.status!=="verified"&&<button disabled={busy==="domain-"+d.id} onClick={()=>verifyDomain(d.id)} className="font-semibold text-slate-900">{busy==="domain-"+d.id?"Checking...":"Verify"}</button>}</div>)}</div></div>}
      </section>
    })}</div>
   </>}
  </div>
 </main>
}
function Metric({icon,label,value,hint}:{icon:React.ReactNode;label:string;value:string;hint:string}){return <div className="rounded-xl border border-slate-200 bg-white p-5"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[#e7f3ff] text-slate-900 [&>svg]:h-5 [&>svg]:w-5">{icon}</div><p className="mt-4 text-xs font-bold text-slate-500">{label}</p><p className="mt-1 text-2xl font-bold text-slate-900">{value}</p><p className="mt-1 text-[11px] text-slate-400">{hint}</p></div>}
function Stat({icon,label,value}:{icon:React.ReactNode;label:string;value:number}){return <div className="rounded-xl bg-slate-50 p-3"><div className="text-slate-900 [&>svg]:h-4 [&>svg]:w-4">{icon}</div><p className="mt-2 text-lg font-bold text-slate-900">{value}</p><p className="text-[10px] font-bold text-slate-400">{label}</p></div>}
