"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, BadgeCheck, CircleDollarSign, Clock3, Loader2, Megaphone, RefreshCw, Send, Users } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";

type Summary={advertisers:number;campaigns:number;awaiting_review:number;scheduled:number;published:number;paid_payments:number;revenue:number;currency:string;failed_publications:number};
type Publication={id:number;campaign_id:number;status:string;attempt_number:number;external_post_id?:string|null;external_post_url?:string|null;error_message?:string|null;created_at:string};

export default function ReportsPage(){
  const router=useRouter();
  const [summary,setSummary]=useState<Summary|null>(null);
  const [publications,setPublications]=useState<Publication[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");

  async function load(){setLoading(true);setError("");try{const [s,p]=await Promise.all([api<Summary>("/api/v1/admin/reports/summary",{},true),api<Publication[]>("/api/v1/publications",{},true)]);setSummary(s);setPublications(p);}catch(e){setError(e instanceof Error?e.message:"Unable to load reports");}finally{setLoading(false)}}
  useEffect(()=>{const user=getSessionUser();if(!user||user.role==="advertiser"){router.replace("/login");return;}load();},[router]);

  return <main className="min-h-screen bg-[#f5f6fa] text-slate-900">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur"><div className="mx-auto flex h-20 max-w-[1500px] items-center gap-4 px-4 sm:px-6 lg:px-8"><Link href="/dashboard" className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200"><ArrowLeft size={18}/></Link><div className="min-w-0 flex-1"><h1 className="font-black text-[#070a45]">Advertising Reports</h1><p className="hidden text-xs text-slate-500 sm:block">Live operational and revenue overview from Meloli advertising data.</p></div><button onClick={load} className="flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-extrabold text-[#070a45]"><RefreshCw size={16}/> Refresh</button></div></header>
    <div className="mx-auto max-w-[1500px] p-4 sm:p-6 lg:p-8">
      {loading?<div className="grid min-h-72 place-items-center"><Loader2 className="animate-spin text-[#e31545]"/></div>:error?<div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm font-semibold text-rose-700">{error}</div>:summary&&<>
        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric icon={<CircleDollarSign/>} label="Confirmed revenue" value={`${summary.currency} ${Number(summary.revenue).toLocaleString(undefined,{minimumFractionDigits:2})}`}/><Metric icon={<Megaphone/>} label="Campaigns" value={String(summary.campaigns)}/><Metric icon={<Users/>} label="Advertisers" value={String(summary.advertisers)}/><Metric icon={<BadgeCheck/>} label="Published" value={String(summary.published)}/><Metric icon={<Clock3/>} label="Awaiting review" value={String(summary.awaiting_review)}/><Metric icon={<Send/>} label="Scheduled" value={String(summary.scheduled)}/><Metric icon={<CircleDollarSign/>} label="Paid transactions" value={String(summary.paid_payments)}/><Metric icon={<RefreshCw/>} label="Failed publish attempts" value={String(summary.failed_publications)}/></section>
        <section className="mt-6 overflow-hidden rounded-[1.6rem] border border-slate-200 bg-white"><div className="border-b border-slate-100 p-5 sm:p-6"><h2 className="font-black text-[#070a45]">Facebook publishing history</h2><p className="mt-1 text-sm text-slate-500">Most recent attempts, including failures that may need a retry.</p></div>{publications.length===0?<div className="p-8 text-sm text-slate-500">No publication attempts yet.</div>:<div className="divide-y divide-slate-100">{publications.slice(0,50).map(p=><div key={p.id} className="grid gap-3 p-5 sm:grid-cols-[100px_1fr_auto] sm:items-center"><div className="text-xs font-black text-slate-400">Campaign #{p.campaign_id}</div><div><div className="flex items-center gap-2"><span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${p.status==="published"?"bg-emerald-50 text-emerald-700":p.status==="failed"?"bg-rose-50 text-rose-700":"bg-amber-50 text-amber-700"}`}>{p.status}</span><span className="text-xs text-slate-400">Attempt {p.attempt_number}</span></div><p className="mt-2 text-sm text-slate-500">{p.error_message||p.external_post_id||"Publishing request prepared"}</p></div><div className="text-right">{p.external_post_url?<a href={p.external_post_url} target="_blank" className="text-sm font-extrabold text-[#e31545]">Open post ↗</a>:<span className="text-xs text-slate-400">{new Date(p.created_at).toLocaleString()}</span>}</div></div>)}</div>}</section>
      </>}
    </div>
  </main>;
}

function Metric({icon,label,value}:{icon:React.ReactNode;label:string;value:string}){return <div className="rounded-[1.45rem] border border-slate-200 bg-white p-5"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[#070a45]/5 text-[#070a45] [&>svg]:h-5 [&>svg]:w-5">{icon}</div><p className="mt-4 text-xs font-black uppercase tracking-wider text-slate-400">{label}</p><p className="mt-1 text-2xl font-black text-[#070a45]">{value}</p></div>}
