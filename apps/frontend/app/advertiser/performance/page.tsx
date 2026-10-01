"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, BarChart3, Eye, Loader2, Megaphone, MessageCircle, MousePointerClick, RefreshCw, Share2, ThumbsUp, TrendingUp, Users } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";

type Performance={campaigns_published:number;campaigns_with_metrics:number;impressions:number;reach:number;engaged_users:number;clicks:number;reactions:number;comments:number;shares:number;video_views:number;engagement_rate:number;click_rate:number};

type Campaign={id:number;title:string;status:string;facebook_post_url?:string|null;published_at?:string|null};
type CampaignPerformance={campaign_id:number;impressions:number|null;reach:number|null;engaged_users:number|null;clicks:number|null;reactions:number|null;comments:number|null;shares:number|null;video_views:number|null;synced_at:string};

type Row={campaign:Campaign;performance:CampaignPerformance|null};

export default function AdvertiserPerformancePage(){
  const router=useRouter();
  const [summary,setSummary]=useState<Performance|null>(null);
  const [rows,setRows]=useState<Row[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");

  async function load(){
    setLoading(true);setError("");
    try{
      const [perf,campaigns]=await Promise.all([api<Performance>("/api/v1/advertiser/performance/summary",{},true),api<Campaign[]>("/api/v1/campaigns",{},true)]);
      setSummary(perf);
      const published=campaigns.filter(c=>c.status==="published");
      const metrics=await Promise.all(published.map(async c=>({campaign:c,performance:await api<CampaignPerformance|null>(`/api/v1/campaigns/${c.id}/performance`,{},true).catch(()=>null)})));
      setRows(metrics);
    }catch(e){setError(e instanceof Error?e.message:"Unable to load performance");}
    finally{setLoading(false);}
  }

  useEffect(()=>{const user=getSessionUser();if(!user||user.role!=="advertiser"){router.replace("/login");return;}load();},[router]);

  return <main className="min-h-screen bg-[#f5f6fa] text-slate-900">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur"><div className="mx-auto flex h-20 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8"><Link href="/advertiser" className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200"><ArrowLeft size={18}/></Link><div className="min-w-0 flex-1"><h1 className="font-black text-[#070a45]">Campaign Performance</h1><p className="hidden text-xs text-slate-500 sm:block">See how your published Meloli adverts are performing on Facebook.</p></div><button onClick={load} className="flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-extrabold text-[#070a45]"><RefreshCw size={16}/> Refresh</button></div></header>

    <div className="mx-auto max-w-7xl p-4 sm:p-6 lg:p-8">
      {loading?<div className="grid min-h-72 place-items-center"><Loader2 className="animate-spin text-[#e31545]"/></div>:error?<div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm font-semibold text-rose-700">{error}</div>:summary&&<>
        <section className="rounded-[1.8rem] bg-[#070a45] p-6 text-white sm:p-8"><div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><p className="text-xs font-black uppercase tracking-[.18em] text-white/45">Audience results</p><h2 className="mt-2 text-3xl font-black">Know what your advertising achieved.</h2><p className="mt-3 max-w-2xl text-sm leading-6 text-white/60">Performance metrics become available after Meloli publishes your advert and the Facebook connection has permission to return Page post insights.</p></div><div className="rounded-2xl bg-white/10 px-4 py-3 text-sm font-bold text-white/80">{summary.campaigns_with_metrics}/{summary.campaigns_published} published adverts synced</div></div></section>

        <section className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4"><Metric icon={<Eye/>} label="Impressions" value={summary.impressions.toLocaleString()}/><Metric icon={<Users/>} label="Reach" value={summary.reach.toLocaleString()}/><Metric icon={<TrendingUp/>} label="Engagement rate" value={`${summary.engagement_rate}%`}/><Metric icon={<MousePointerClick/>} label="Click rate" value={`${summary.click_rate}%`}/><Metric icon={<MousePointerClick/>} label="Clicks" value={summary.clicks.toLocaleString()}/><Metric icon={<ThumbsUp/>} label="Reactions" value={summary.reactions.toLocaleString()}/><Metric icon={<MessageCircle/>} label="Comments" value={summary.comments.toLocaleString()}/><Metric icon={<Share2/>} label="Shares" value={summary.shares.toLocaleString()}/></section>

        <section className="mt-6 overflow-hidden rounded-[1.6rem] border border-slate-200 bg-white"><div className="border-b border-slate-100 p-5 sm:p-6"><h2 className="font-black text-[#070a45]">Published campaign results</h2><p className="mt-1 text-sm text-slate-500">A breakdown of the Facebook performance currently stored for each advert.</p></div>{rows.length===0?<Empty/>:<div className="divide-y divide-slate-100">{rows.map(({campaign,performance})=><article key={campaign.id} className="p-5 sm:p-6"><div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start"><div><div className="flex items-center gap-2"><div className="grid h-9 w-9 place-items-center rounded-xl bg-[#070a45]/5 text-[#070a45]"><Megaphone size={17}/></div><div><h3 className="font-extrabold text-slate-900">{campaign.title}</h3><p className="text-xs font-semibold text-slate-400">{campaign.published_at?`Published ${new Date(campaign.published_at).toLocaleString()}`:`Campaign #${campaign.id}`}</p></div></div></div>{campaign.facebook_post_url&&<a href={campaign.facebook_post_url} target="_blank" className="text-sm font-extrabold text-[#e31545]">Open Facebook post ↗</a>}</div>{performance?<div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8"><Mini label="Reach" value={performance.reach}/><Mini label="Impressions" value={performance.impressions}/><Mini label="Clicks" value={performance.clicks}/><Mini label="Engaged" value={performance.engaged_users}/><Mini label="Reactions" value={performance.reactions}/><Mini label="Comments" value={performance.comments}/><Mini label="Shares" value={performance.shares}/><Mini label="Video views" value={performance.video_views}/></div>:<div className="mt-5 rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">Performance has not been synced for this advert yet. Meloli staff can refresh the Facebook metrics after publication.</div>}</article>)}</div>}</section>
      </>}
    </div>
  </main>;
}

function Metric({icon,label,value}:{icon:React.ReactNode;label:string;value:string}){return <div className="rounded-[1.35rem] border border-slate-200 bg-white p-4 sm:p-5"><div className="text-[#e31545] [&>svg]:h-5 [&>svg]:w-5">{icon}</div><p className="mt-4 text-2xl font-black text-[#070a45] sm:text-3xl">{value}</p><p className="mt-1 text-xs font-bold text-slate-600 sm:text-sm">{label}</p></div>}
function Mini({label,value}:{label:string;value:number|null}){return <div className="rounded-xl bg-slate-50 p-3"><p className="text-[10px] font-black uppercase tracking-wider text-slate-400">{label}</p><p className="mt-1 text-lg font-black text-[#070a45]">{value==null?"—":value.toLocaleString()}</p></div>}
function Empty(){return <div className="p-10 text-center"><div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-[#070a45]/5 text-[#070a45]"><BarChart3/></div><h3 className="mt-4 font-black text-[#070a45]">No published campaigns yet</h3><p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">Performance analytics will appear here after your first approved advert has been published.</p></div>}
