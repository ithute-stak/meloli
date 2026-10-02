"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, AlertTriangle, ArrowLeft, CheckCircle2, Clock3, Loader2, RefreshCw, RotateCcw } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";
import { useRealtimeTopics } from "@/app/components/RealtimeBridge";

type Job={
  job_key:string;
  interval_seconds:number;
  last_started_at?:string|null;
  last_completed_at?:string|null;
  last_status:string;
  last_result?:string|null;
  last_error?:string|null;
  run_count:number;
  failure_count:number;
  due:boolean;
  stalled?:boolean;
};

const label=(value:string)=>value.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
const duration=(seconds:number)=>{
  if(seconds<60)return seconds+"s";
  if(seconds<3600)return Math.round(seconds/60)+"m";
  if(seconds<86400)return Math.round(seconds/3600)+"h";
  return Math.round(seconds/86400)+"d";
};

export default function AutomationPage(){
  const router=useRouter();
  const [jobs,setJobs]=useState<Job[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [runningJob,setRunningJob]=useState<string|null>(null);

  async function load(silent=false){
    if(!silent)setLoading(true);
    try{setJobs(await api<Job[]>("/api/v1/admin/automation/jobs",{},true));setError("")}
    catch(e){setError(e instanceof Error?e.message:"Unable to load automation health")}
    finally{if(!silent)setLoading(false)}
  }

  useEffect(()=>{
    const user=getSessionUser();
    if(!user||user.role!=="super_admin"){router.replace("/dashboard");return}
    load();
    const timer=window.setInterval(()=>load(true),30000);
    return()=>window.clearInterval(timer);
  },[router]);
  useRealtimeTopics(["automation"],()=>load(true));

  async function runNow(jobKey:string){
    setRunningJob(jobKey);
    try{
      await api(`/api/v1/admin/automation/jobs/${encodeURIComponent(jobKey)}/run-now`,{method:"POST"},true);
      await load(true);
    }catch(e){
      setError(e instanceof Error?e.message:"Unable to queue automation job");
    }finally{
      setRunningJob(null);
    }
  }

  const summary=useMemo(()=>({
    total:jobs.length,
    healthy:jobs.filter(j=>j.last_status==="success").length,
    failed:jobs.filter(j=>j.last_status==="failed").length,
    due:jobs.filter(j=>j.due).length,
    stalled:jobs.filter(j=>j.stalled).length,
  }),[jobs]);

  return <main className="fb-page">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white shadow-sm">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-3 sm:px-4 lg:px-6">
        <Link href="/dashboard" className="fb-icon-button"><ArrowLeft size={18}/></Link>
        <div className="min-w-0 flex-1"><h1 className="text-[17px] font-bold text-slate-900">Automation health</h1><p className="hidden text-xs text-[#65676b] sm:block">Background jobs, cadences, failures and recent results.</p></div>
        <button onClick={()=>load()} className="fb-icon-button" aria-label="Refresh automation health"><RefreshCw size={17}/></button>
      </div>
    </header>

    <div className="mx-auto max-w-[1400px] p-3 sm:p-4 lg:p-6">
      {error&&<div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}
      {loading?<div className="grid min-h-64 place-items-center"><Loader2 className="animate-spin text-[#0866ff]"/></div>:<>
        <section className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          <Kpi icon={<Activity/>} label="Automation jobs" value={summary.total}/>
          <Kpi icon={<CheckCircle2/>} label="Healthy" value={summary.healthy} good/>
          <Kpi icon={<AlertTriangle/>} label="Failed" value={summary.failed} bad/>
          <Kpi icon={<Clock3/>} label="Due now" value={summary.due}/>
          <Kpi icon={<RotateCcw/>} label="Stalled" value={summary.stalled} bad={summary.stalled>0}/>
        </section>

        <section className="mt-4 fb-card overflow-hidden">
          <div className="border-b border-slate-200 p-4"><h2 className="font-bold text-slate-900">Scheduler jobs</h2><p className="mt-0.5 text-sm text-[#65676b]">Each routine runs independently at its configured cadence.</p></div>
          {jobs.length===0?<div className="p-8 text-sm text-[#65676b]">The scheduler has not registered jobs yet.</div>:<div className="divide-y divide-slate-100">{jobs.map(job=><article key={job.job_key} className="p-4">
            <div className="grid gap-4 lg:grid-cols-[minmax(220px,1fr)_110px_100px_100px_110px_120px] lg:items-center">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold text-slate-900">{label(job.job_key)}</h3><Status value={job.last_status}/>{job.due&&<span className="rounded-full bg-amber-50 px-2 py-1 text-[10px] font-semibold text-amber-700">Due</span>}{job.stalled&&<span className="rounded-full bg-rose-50 px-2 py-1 text-[10px] font-semibold text-rose-700">Stalled</span>}</div>
                <p className="mt-1 text-xs text-[#65676b]">{job.last_error||job.last_result||"No result recorded yet."}</p>
              </div>
              <Cell label="Cadence" value={duration(job.interval_seconds)}/>
              <Cell label="Runs" value={String(job.run_count)}/>
              <Cell label="Failures" value={String(job.failure_count)}/>
              <Cell label="Last run" value={job.last_completed_at?new Date(job.last_completed_at).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}):"Never"}/>
              <button
                onClick={()=>runNow(job.job_key)}
                disabled={runningJob===job.job_key||job.last_status==="running"}
                className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[#e7f3ff] px-3 text-xs font-bold text-[#0866ff] transition hover:bg-[#d8eaff] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {runningJob===job.job_key?<Loader2 size={14} className="animate-spin"/>:<RotateCcw size={14}/>}
                Run now
              </button>
            </div>
          </article>)}</div>}
        </section>

        <section className="mt-4 rounded-xl border border-blue-200 bg-[#e7f3ff] p-4">
          <div className="flex items-start gap-3"><RotateCcw className="mt-0.5 shrink-0 text-[#0866ff]" size={18}/><div><p className="font-bold text-slate-900">Automated routines currently covered</p><p className="mt-1 text-sm leading-6 text-[#65676b]">Notification delivery, Meta webhook processing, campaign reminders, competition closing/sync, Facebook KPI synchronization, Meta/domain/backup health checks, daily Page digests, subscription lifecycle, review-presence cleanup, corporate invoices and scheduled Facebook publishing.</p></div></div>
        </section>
      </>}
    </div>
  </main>;
}

function Kpi({icon,label,value,good,bad}:{icon:React.ReactNode;label:string;value:number;good?:boolean;bad?:boolean}){const tone=bad?"text-rose-700 bg-rose-50":good?"text-emerald-700 bg-emerald-50":"text-[#0866ff] bg-[#e7f3ff]";return <div className="fb-card p-3 sm:p-4"><div className={"grid h-9 w-9 place-items-center rounded-full "+tone+" [&>svg]:h-4 [&>svg]:w-4"}>{icon}</div><p className="mt-3 text-xl font-bold text-slate-900 sm:text-2xl">{value}</p><p className="mt-0.5 text-xs font-semibold text-[#65676b]">{label}</p></div>}
function Status({value}:{value:string}){const cls=value==="success"?"bg-emerald-50 text-emerald-700":value==="failed"?"bg-rose-50 text-rose-700":value==="running"?"bg-blue-50 text-blue-700":value==="queued"?"bg-amber-50 text-amber-700":"bg-slate-100 text-slate-600";return <span className={"rounded-full px-2 py-1 text-[10px] font-semibold "+cls}>{value}</span>}
function Cell({label,value}:{label:string;value:string}){return <div><p className="text-[10px] font-semibold text-[#8a8d91]">{label}</p><p className="mt-1 text-sm font-semibold text-slate-800">{value}</p></div>}
