"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, BarChart3, Eye, Loader2, Megaphone, MousePointerClick, RefreshCw, Share2, ThumbsUp, TrendingUp, Users } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";
import { useRealtimeTopics } from "@/app/components/RealtimeBridge";

type Summary={advertisers:number;campaigns:number;awaiting_review:number;scheduled:number;published:number;paid_payments:number;revenue:number;currency:string;failed_publications:number};
type Performance={campaigns_published:number;campaigns_with_metrics:number;impressions:number;reach:number;engaged_users:number;clicks:number;reactions:number;comments:number;shares:number;video_views:number;engagement_rate:number;click_rate:number};
type Publication={id:number;campaign_id:number;status:string;attempt_number:number;external_post_id?:string|null;external_post_url?:string|null;error_message?:string|null;created_at:string};
type BulkSync={eligible:number;synced:number;failed:number;failures:string[]};

export default function ReportsPage(){
  const router=useRouter();
  const [summary,setSummary]=useState<Summary|null>(null);
  const [performance,setPerformance]=useState<Performance|null>(null);
  const [publications,setPublications]=useState<Publication[]>([]);
  const [loading,setLoading]=useState(true);
  const [syncing,setSyncing]=useState(false);
  const [canSync,setCanSync]=useState(false);
  const [syncMessage,setSyncMessage]=useState("");
  const [error,setError]=useState("");

  async function load(){
    setLoading(true); setError("");
    try{
      const [s,p,perf]=await Promise.all([
        api<Summary>("/api/v1/admin/reports/summary",{},true),
        api<Publication[]>("/api/v1/publications",{},true),
        api<Performance>("/api/v1/admin/performance/summary",{},true),
      ]);
      setSummary(s); setPublications(p); setPerformance(perf);
    }catch(e){setError(e instanceof Error?e.message:"Unable to load reports")}
    finally{setLoading(false)}
  }

  useEffect(()=>{
    const user=getSessionUser();
    if(!user||user.role==="advertiser"){router.replace("/login");return}
    setCanSync(["publisher","super_admin"].includes(user.role));
    load();
  },[router]);
  useRealtimeTopics(["performance","campaign"],()=>{load()});

  async function syncPerformance(){
    setSyncing(true); setError(""); setSyncMessage("");
    try{
      const result=await api<BulkSync>("/api/v1/admin/performance/sync",{method:"POST"},true);
      setSyncMessage("Facebook KPIs refreshed for "+result.synced+" of "+result.eligible+" eligible campaigns"+(result.failed?"; "+result.failed+" failed":"")+".");
      await load();
    }catch(e){setError(e instanceof Error?e.message:"Unable to sync Facebook KPIs")}
    finally{setSyncing(false)}
  }

  const approvalRate=summary?.campaigns?Math.round(((summary.published+summary.scheduled)/summary.campaigns)*100):0;
  const publishRate=summary?.campaigns?Math.round((summary.published/summary.campaigns)*100):0;
  const reviewShare=summary?.campaigns?Math.round((summary.awaiting_review/summary.campaigns)*100):0;
  const failureRate=(summary?.published||0)+(summary?.failed_publications||0)
    ?Math.round(((summary?.failed_publications||0)/((summary?.published||0)+(summary?.failed_publications||0)))*100):0;
  const metricCoverage=performance?.campaigns_published?Math.round((performance.campaigns_with_metrics/performance.campaigns_published)*100):0;

  return <main className="fb-page">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white shadow-sm">
      <div className="mx-auto flex h-16 max-w-[1500px] items-center gap-3 px-3 sm:px-4 lg:px-6">
        <Link href="/dashboard" className="fb-icon-button"><ArrowLeft size={18}/></Link>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[17px] font-bold text-slate-900">Advertising analytics</h1>
          <p className="hidden text-xs text-[#65676b] sm:block">Commercial, workflow and Facebook performance intelligence.</p>
        </div>
        <div className="flex items-center gap-2">
          {canSync&&<button disabled={syncing} onClick={syncPerformance} className="fb-primary hidden h-10 items-center gap-2 px-4 text-sm disabled:opacity-50 sm:flex">{syncing?<Loader2 size={16} className="animate-spin"/>:<RefreshCw size={16}/>} Sync Facebook</button>}
          <button onClick={load} className="fb-icon-button" aria-label="Refresh analytics"><RefreshCw size={17}/></button>
        </div>
      </div>
    </header>

    <div className="mx-auto max-w-[1500px] p-3 pb-20 sm:p-4 lg:p-6">
      {syncMessage&&<div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-700">{syncMessage}</div>}
      {loading?<div className="grid min-h-72 place-items-center"><Loader2 className="animate-spin text-[#0866ff]"/></div>
      :error?<div className="rounded-lg border border-rose-200 bg-rose-50 p-5 text-sm font-semibold text-rose-700">{error}</div>
      :summary&&<>
        <section className="mb-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-[#0866ff]">Executive overview</p>
              <h2 className="mt-1 text-2xl font-bold text-slate-900">Business and publishing performance</h2>
              <p className="mt-1 text-sm text-[#65676b]">Revenue, campaign throughput and Facebook audience results in one view.</p>
            </div>
            <div className="rounded-lg bg-[#f0f2f5] px-3 py-2 text-xs font-semibold text-[#65676b]">Live operational data</div>
          </div>
        </section>

        <section className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <Metric label="Revenue" value={(summary.currency||"LSL")+" "+Number(summary.revenue).toLocaleString(undefined,{maximumFractionDigits:0})} detail={summary.paid_payments+" confirmed payments"}/>
          <Metric label="Campaigns" value={String(summary.campaigns)} detail="Total submitted"/>
          <Metric label="Advertisers" value={String(summary.advertisers)} detail="Customer base"/>
          <Metric label="Published" value={String(summary.published)} detail={publishRate+"% publish rate"}/>
          <Metric label="In review" value={String(summary.awaiting_review)} detail={reviewShare+"% of volume"}/>
          <Metric label="Scheduled" value={String(summary.scheduled)} detail="Approved upcoming"/>
        </section>

        <section className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(340px,.45fr)]">
          <div className="space-y-4">
            <div className="fb-card p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <div><h3 className="font-bold text-slate-900">Operational funnel</h3><p className="mt-0.5 text-sm text-[#65676b]">How effectively campaigns progress through the workflow.</p></div>
                <BarChart3 size={20} className="text-[#0866ff]"/>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <RateCard label="Approval progression" value={approvalRate} description="Scheduled or published"/>
                <RateCard label="Publish rate" value={publishRate} description="Campaigns made live"/>
                <RateCard label="Editorial backlog" value={reviewShare} description="Awaiting review" warning/>
                <RateCard label="Publish failures" value={failureRate} description="Failed Meta attempts" danger/>
              </div>
            </div>

            {performance&&<div className="fb-card p-4 sm:p-5">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div><p className="text-sm font-semibold text-[#0866ff]">Facebook performance</p><h3 className="mt-0.5 text-lg font-bold text-slate-900">Audience and engagement KPIs</h3><p className="mt-1 text-sm text-[#65676b]">Synced results from published tenant campaigns.</p></div>
                <div className="text-xs font-semibold text-[#65676b]">{performance.campaigns_with_metrics}/{performance.campaigns_published} campaigns synced · {metricCoverage}% coverage</div>
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Insight icon={<Eye/>} label="Impressions" value={performance.impressions.toLocaleString()}/>
                <Insight icon={<Users/>} label="Reach" value={performance.reach.toLocaleString()}/>
                <Insight icon={<TrendingUp/>} label="Engagement rate" value={performance.engagement_rate+"%"}/>
                <Insight icon={<MousePointerClick/>} label="Click rate" value={performance.click_rate+"%"}/>
                <Insight icon={<MousePointerClick/>} label="Clicks" value={performance.clicks.toLocaleString()}/>
                <Insight icon={<ThumbsUp/>} label="Reactions" value={performance.reactions.toLocaleString()}/>
                <Insight icon={<Share2/>} label="Shares" value={performance.shares.toLocaleString()}/>
                <Insight icon={<Megaphone/>} label="Engaged users" value={performance.engaged_users.toLocaleString()}/>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Progress label="Engagement efficiency" value={Math.min(100,Math.max(0,performance.engagement_rate))}/>
                <Progress label="Click efficiency" value={Math.min(100,Math.max(0,performance.click_rate))}/>
              </div>
            </div>}
          </div>

          <aside className="space-y-4">
            <div className="fb-card p-4">
              <h3 className="font-bold text-slate-900">Commercial efficiency</h3>
              <div className="mt-4 space-y-3">
                <SmallKpi label="Revenue per advertiser" value={summary.advertisers?(summary.currency+" "+Math.round(summary.revenue/summary.advertisers).toLocaleString()):"—"}/>
                <SmallKpi label="Payments per campaign" value={summary.campaigns?(summary.paid_payments/summary.campaigns).toFixed(2):"0.00"}/>
                <SmallKpi label="Published per advertiser" value={summary.advertisers?(summary.published/summary.advertisers).toFixed(2):"0.00"}/>
              </div>
            </div>

            <div className={"rounded-xl border p-4 "+(failureRate>0?"border-rose-200 bg-rose-50":"border-emerald-200 bg-emerald-50")}>
              <div className="flex items-start gap-3">
                <div className={"grid h-9 w-9 shrink-0 place-items-center rounded-full "+(failureRate>0?"bg-rose-100 text-rose-700":"bg-emerald-100 text-emerald-700")}><RefreshCw size={17}/></div>
                <div><p className="font-bold text-slate-900">Publishing reliability</p><p className="mt-1 text-sm leading-5 text-[#65676b]">{summary.failed_publications} failed attempts, a {failureRate}% failure rate.</p></div>
              </div>
            </div>
          </aside>
        </section>

        <section className="mt-4 fb-card overflow-hidden">
          <div className="flex flex-col gap-2 border-b border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div><h2 className="font-bold text-slate-900">Facebook publishing history</h2><p className="mt-0.5 text-sm text-[#65676b]">Attempts, failures and successful post links.</p></div>
            <span className="text-xs font-semibold text-[#65676b]">{publications.length} recorded attempts</span>
          </div>
          {publications.length===0?<div className="p-8 text-sm text-[#65676b]">No publication attempts yet.</div>:<div className="divide-y divide-slate-100">{publications.slice(0,50).map(p=><div key={p.id} className="flex flex-col gap-3 p-4 sm:grid sm:grid-cols-[100px_minmax(0,1fr)_auto] sm:items-center">
            <div className="text-xs font-semibold text-[#65676b]">Campaign #{p.campaign_id}</div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2"><span className={"rounded-full px-2.5 py-1 text-[11px] font-semibold "+(p.status==="published"?"bg-emerald-50 text-emerald-700":p.status==="failed"?"bg-rose-50 text-rose-700":"bg-amber-50 text-amber-700")}>{p.status}</span><span className="text-xs text-[#65676b]">Attempt {p.attempt_number}</span></div>
              <p className="mt-1 line-clamp-2 text-sm text-[#65676b]">{p.error_message||p.external_post_id||"Publishing request prepared"}</p>
            </div>
            <div className="sm:text-right">{p.external_post_url?<a href={p.external_post_url} target="_blank" className="text-sm font-semibold text-[#0866ff]">Open post ↗</a>:<span className="text-xs text-[#65676b]">{new Date(p.created_at).toLocaleString()}</span>}</div>
          </div>)}</div>}
        </section>
      </>}
    </div>
  </main>;
}

function Metric({label,value,detail}:{label:string;value:string;detail:string}){return <div className="fb-card min-w-0 p-3 sm:p-4"><p className="truncate text-xs font-semibold text-[#65676b]">{label}</p><p className="mt-1 truncate text-xl font-bold text-slate-900 sm:text-2xl">{value}</p><p className="mt-1 truncate text-[11px] text-[#8a8d91]">{detail}</p></div>}
function RateCard({label,value,description,warning,danger}:{label:string;value:number;description:string;warning?:boolean;danger?:boolean}){const tone=danger&&value>0?"bg-rose-50 text-rose-700":warning&&value>0?"bg-amber-50 text-amber-700":"bg-[#e7f3ff] text-[#0866ff]";return <div className={"rounded-lg p-3 "+tone}><p className="text-xs font-semibold">{label}</p><p className="mt-2 text-3xl font-bold">{value}%</p><p className="mt-1 text-[11px] opacity-75">{description}</p></div>}
function Insight({icon,label,value}:{icon:React.ReactNode;label:string;value:string}){return <div className="rounded-lg bg-[#f7f8fa] p-3"><div className="text-[#0866ff] [&>svg]:h-4 [&>svg]:w-4">{icon}</div><p className="mt-3 text-lg font-bold text-slate-900">{value}</p><p className="mt-0.5 text-[11px] font-semibold text-[#65676b]">{label}</p></div>}
function Progress({label,value}:{label:string;value:number}){return <div className="rounded-lg border border-slate-200 p-3"><div className="flex items-center justify-between text-xs"><span className="font-semibold text-slate-700">{label}</span><span className="font-bold text-[#0866ff]">{value}%</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e4e6eb]"><div className="h-full rounded-full bg-[#0866ff]" style={{width:value+"%"}}/></div></div>}
function SmallKpi({label,value}:{label:string;value:string}){return <div className="flex items-center justify-between gap-3 rounded-lg bg-[#f7f8fa] px-3 py-2.5"><span className="text-xs font-semibold text-[#65676b]">{label}</span><span className="text-sm font-bold text-slate-900">{value}</span></div>}
