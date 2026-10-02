"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, CalendarDays, CheckCircle2, Clock3, Loader2, Megaphone, Search, Send, XCircle } from "lucide-react";
import { API_URL, api, getSessionUser, SessionUser } from "@/lib/api";

type MediaItem={id:number;url:string;content_type:string;position:number};
type Campaign = {
  id:number; advertiser_id:number; package_id:number; title:string; caption:string;
  media_url?:string|null; media_items:MediaItem[]; destination_url?:string|null; preferred_publish_at?:string|null;
  scheduled_publish_at?:string|null; status:string; reviewer_note?:string|null; created_at:string;
  facebook_post_url?:string|null; published_at?:string|null; cancelled_at?:string|null; cancellation_reason?:string|null; proof_status:string; proof_feedback?:string|null; proof_requested_at?:string|null; proof_approved_at?:string|null;
};

const statusLabel=(s:string)=>s.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());

export default function CampaignsPage(){
  const router=useRouter();
  const [user,setUser]=useState<SessionUser|null>(null);
  const [items,setItems]=useState<Campaign[]>([]);
  const [selected,setSelected]=useState<Campaign|null>(null);
  const [query,setQuery]=useState("");
  const [note,setNote]=useState("");
  const [schedule,setSchedule]=useState("");
  const [loading,setLoading]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");

  async function load(){
    setLoading(true); setError("");
    try{const data=await api<Campaign[]>("/api/v1/campaigns",{},true);setItems(data);if(selected){setSelected(data.find(x=>x.id===selected.id)||null)}}
    catch(e){setError(e instanceof Error?e.message:"Unable to load campaigns")}
    finally{setLoading(false)}
  }

  useEffect(()=>{const current=getSessionUser();if(!current||current.role==="advertiser"){router.replace("/login");return;}setUser(current);load();},[router]);
  const filtered=useMemo(()=>items.filter(x=>x.title.toLowerCase().includes(query.toLowerCase())||x.caption.toLowerCase().includes(query.toLowerCase())),[items,query]);

  async function decide(status:string){
    if(!selected)return; setSaving(true); setError(""); setMessage("");
    try{
      await api(`/api/v1/campaigns/${selected.id}/decision`,{method:"PATCH",body:JSON.stringify({status,reviewer_note:note||null,scheduled_publish_at:status==="scheduled"&&schedule?new Date(schedule).toISOString():null})},true);
      setNote("");setSchedule("");setMessage(`Campaign ${statusLabel(status).toLowerCase()}.`);await load();
    }catch(e){setError(e instanceof Error?e.message:"Unable to update campaign")}
    finally{setSaving(false)}
  }

  async function publish(){
    if(!selected)return; setSaving(true); setError(""); setMessage("");
    try{
      await api(`/api/v1/campaigns/${selected.id}/publish`,{method:"POST"},true);
      setMessage("Advert published to the configured Meloli Facebook Page.");
      await load();
    }catch(e){setError(e instanceof Error?e.message:"Publishing failed")}
    finally{setSaving(false)}
  }

  const mediaHref=(url:string)=>url.startsWith("http://")||url.startsWith("https://")?url:API_URL+url;
  const canPublish=user?.role==="publisher"||user?.role==="super_admin";

  return <main className="min-h-screen bg-[#f5f6fa] text-slate-900">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur"><div className="mx-auto flex h-20 max-w-[1500px] items-center gap-4 px-4 sm:px-6 lg:px-8"><Link href="/dashboard" className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200"><ArrowLeft size={18}/></Link><div className="min-w-0 flex-1"><h1 className="font-black text-[#070a45]">Campaign Review</h1><p className="hidden text-xs text-slate-500 sm:block">Review paid submissions, approve, schedule and publish to Facebook.</p></div><span className="rounded-full bg-[#070a45]/5 px-3 py-1.5 text-xs font-black text-[#070a45]">{items.length} campaigns</span></div></header>
    <div className="mx-auto grid max-w-[1500px] gap-6 p-4 sm:p-6 lg:grid-cols-[1fr_430px] lg:p-8">
      <section className="overflow-hidden rounded-[1.6rem] border border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-5"><div className="flex h-12 items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4"><Search size={17} className="text-slate-400"/><input value={query} onChange={e=>setQuery(e.target.value)} className="w-full bg-transparent text-sm outline-none" placeholder="Search campaigns..."/></div></div>
        {loading?<div className="grid min-h-72 place-items-center"><Loader2 className="animate-spin text-[#e31545]"/></div>:<div className="divide-y divide-slate-100">{filtered.map(c=><button key={c.id} onClick={()=>{setSelected(c);setNote(c.reviewer_note||"");setError("");setMessage("")}} className={`grid w-full gap-3 p-5 text-left transition hover:bg-slate-50 sm:grid-cols-[1fr_auto] ${selected?.id===c.id?"bg-indigo-50/60":""}`}><div><div className="flex flex-wrap items-center gap-2"><p className="font-extrabold text-slate-900">{c.title}</p><Status value={c.cancelled_at?"cancelled":c.status}/></div><p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-500">{c.caption}</p></div><div className="text-xs font-bold text-slate-400">#{c.id}</div></button>)}</div>}
      </section>
      <aside className="h-fit lg:sticky lg:top-28">{selected?<div className="rounded-[1.6rem] border border-slate-200 bg-white p-5 sm:p-6"><div className="flex items-start gap-3"><div className="grid h-11 w-11 place-items-center rounded-xl bg-[#070a45]/5 text-[#070a45]"><Megaphone size={19}/></div><div><h2 className="font-black text-[#070a45]">{selected.title}</h2><p className="mt-1 text-xs text-slate-400">Campaign #{selected.id} · Advertiser #{selected.advertiser_id}</p></div></div><div className="mt-5 rounded-2xl bg-slate-50 p-4 text-sm leading-6 text-slate-700 whitespace-pre-wrap">{selected.caption}</div>{selected.media_items?.length>0?<div className="mt-4 grid grid-cols-2 gap-2">{selected.media_items.map((item,index)=><a key={item.id} href={mediaHref(item.url)} target="_blank" className="rounded-xl border border-slate-200 bg-slate-50 p-2 text-xs font-extrabold text-[#070a45]">Media {index+1} · {item.content_type.startsWith("image/")?"image":"video"} ↗</a>)}</div>:selected.media_url&&<a href={mediaHref(selected.media_url)} target="_blank" className="mt-4 block truncate text-sm font-bold text-[#e31545]">Open campaign media ↗</a>}{selected.facebook_post_url&&<a href={selected.facebook_post_url} target="_blank" className="mt-3 block truncate text-sm font-black text-emerald-700">Open published Facebook post ↗</a>}<div className="mt-5 grid grid-cols-2 gap-3"><Mini label="Status" value={selected.cancelled_at?"Cancelled":statusLabel(selected.status)}/><Mini label="Final proof" value={statusLabel(selected.proof_status)}/><Mini label="Preferred" value={selected.preferred_publish_at?new Date(selected.preferred_publish_at).toLocaleString():"Not specified"}/></div>{selected.cancelled_at&&<div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><p className="text-xs font-black uppercase tracking-wider text-slate-400">Cancellation</p><p className="mt-2 text-sm text-slate-700">{selected.cancellation_reason||"Cancelled"}</p></div>}<label className="mt-5 block"><span className="mb-2 block text-xs font-black uppercase tracking-wider text-slate-500">Reviewer note</span><textarea value={note} onChange={e=>setNote(e.target.value)} rows={4} className="w-full rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm outline-none focus:border-[#070a45]" placeholder="Required when requesting changes..."/></label><label className="mt-4 block"><span className="mb-2 block text-xs font-black uppercase tracking-wider text-slate-500">Publishing date</span><input type="datetime-local" value={schedule} onChange={e=>setSchedule(e.target.value)} className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-3 text-sm outline-none"/></label>{error&&<div className="mt-4 rounded-xl bg-rose-50 p-3 text-sm font-semibold text-rose-700">{error}</div>}{message&&<div className="mt-4 rounded-xl bg-emerald-50 p-3 text-sm font-semibold text-emerald-700">{message}</div>}<div className={"mt-5 grid gap-2 sm:grid-cols-2 "+(selected.cancelled_at?"pointer-events-none opacity-40":"")}><Action disabled={saving} onClick={()=>decide("changes_requested")} label="Request changes" icon={<Clock3/>}/><Action disabled={saving} onClick={()=>decide("rejected")} label="Reject" icon={<XCircle/>}/><Action disabled={saving} onClick={()=>decide("approved")} label="Approve & send proof" icon={<CheckCircle2/>} primary/><Action disabled={saving||!schedule||selected.proof_status!=="approved"} onClick={()=>decide("scheduled")} label="Schedule" icon={<CalendarDays/>} primary/></div>{canPublish&&["approved","scheduled"].includes(selected.status)&&<button disabled={saving||selected.proof_status!=="approved"} onClick={publish} className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-[#e31545] text-sm font-black text-white disabled:opacity-40">{saving?<Loader2 size={17} className="animate-spin"/>:<Send size={17}/>} Publish to Facebook</button>}</div>:<div className="rounded-[1.6rem] border border-dashed border-slate-300 bg-white p-8 text-center"><Megaphone className="mx-auto text-slate-300"/><p className="mt-4 font-black text-[#070a45]">Select a campaign</p><p className="mt-2 text-sm leading-6 text-slate-500">Choose a submission from the queue to review its content and make an editorial decision.</p></div>}</aside>
    </div>
  </main>;
}

function Status({value}:{value:string}){const cls=value==="published"?"bg-emerald-100 text-emerald-800":value==="approved"||value==="scheduled"?"bg-emerald-50 text-emerald-700":value==="changes_requested"||value==="rejected"?"bg-rose-50 text-rose-700":value==="cancelled"?"bg-slate-200 text-slate-700":value==="payment_pending"?"bg-slate-100 text-slate-600":"bg-amber-50 text-amber-700";return <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${cls}`}>{statusLabel(value)}</span>}
function Mini({label,value}:{label:string;value:string}){return <div className="rounded-xl border border-slate-100 p-3"><p className="text-[10px] font-black uppercase tracking-wider text-slate-400">{label}</p><p className="mt-1 text-xs font-bold text-slate-700">{value}</p></div>}
function Action({label,icon,onClick,disabled,primary}:{label:string;icon:React.ReactNode;onClick:()=>void;disabled?:boolean;primary?:boolean}){return <button disabled={disabled} onClick={onClick} className={`flex items-center justify-center gap-2 rounded-xl px-3 py-3 text-sm font-extrabold disabled:opacity-40 ${primary?"bg-[#070a45] text-white":"border border-slate-200 bg-white text-slate-700"}`}><span className="[&>svg]:h-4 [&>svg]:w-4">{icon}</span>{label}</button>}
