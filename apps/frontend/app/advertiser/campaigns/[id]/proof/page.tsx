"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, CheckCircle2, ExternalLink, Loader2, MessageSquareWarning } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";

type MediaItem={id:number;url:string;content_type:string;position:number};
type Campaign={
  id:number;title:string;caption:string;media_url?:string|null;media_items:MediaItem[];destination_url?:string|null;
  status:string;proof_status:string;proof_feedback?:string|null;proof_requested_at?:string|null;cancelled_at?:string|null;
};

export default function ProofReviewPage(){
  const router=useRouter(); const params=useParams<{id:string}>(); const id=Number(params.id);
  const [campaign,setCampaign]=useState<Campaign|null>(null); const [feedback,setFeedback]=useState("");
  const [busy,setBusy]=useState(""); const [error,setError]=useState(""); const [message,setMessage]=useState("");

  async function load(){
    const rows=await api<Campaign[]>("/api/v1/campaigns",{},true);
    const row=rows.find(x=>x.id===id);
    if(!row)throw new Error("Campaign not found");
    setCampaign(row);
    setFeedback(row.proof_feedback||"");
  }
  useEffect(()=>{const u=getSessionUser();if(!u||u.role!=="advertiser"){router.replace("/login");return;}load().catch(e=>setError(e.message));},[id,router]);

  async function decide(decision:"approved"|"changes_requested",e?:FormEvent){
    e?.preventDefault();setBusy(decision);setError("");setMessage("");
    try{
      const result=await api<{proof_status:string}>("/api/v1/campaigns/"+id+"/proof/decision",{method:"POST",body:JSON.stringify({decision,feedback:feedback||null})},true);
      setMessage(result.proof_status==="approved"?"Final proof approved. Meloli can now schedule or publish this advert.":"Changes sent back to Meloli.");
      await load();
    }catch(err){setError(err instanceof Error?err.message:"Unable to update final proof")}finally{setBusy("")}
  }

  return <main className="min-h-screen bg-[#f5f6fa] text-slate-900"><header className="border-b border-slate-200 bg-white"><div className="mx-auto flex h-20 max-w-4xl items-center gap-4 px-4 sm:px-6"><Link href="/advertiser" className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200"><ArrowLeft size={18}/></Link><div><h1 className="font-black text-[#070a45]">Final Advert Proof</h1><p className="text-xs text-slate-500">Approve exactly what Meloli will publish, or request final corrections.</p></div></div></header><div className="mx-auto max-w-4xl p-4 sm:p-6 lg:p-8">{error&&<div className="mb-5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}{message&&<div className="mb-5 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-700">{message}</div>}{!campaign?<div className="grid min-h-56 place-items-center"><Loader2 className="animate-spin text-[#e31545]"/></div>:<div className="space-y-6"><section className="overflow-hidden rounded-[1.7rem] border border-slate-200 bg-white"><div className="bg-[#070a45] p-6 text-white"><p className="text-xs font-black uppercase tracking-[.18em] text-white/45">Campaign #{campaign.id}</p><h2 className="mt-2 text-2xl font-black">{campaign.title}</h2><div className="mt-4"><span className={"rounded-full px-3 py-1.5 text-xs font-extrabold "+(campaign.proof_status==="approved"?"bg-emerald-400 text-emerald-950":campaign.proof_status==="changes_requested"?"bg-rose-400 text-rose-950":"bg-amber-300 text-amber-950")}>{campaign.proof_status.replaceAll("_"," ")}</span></div></div><div className="p-6"><p className="text-xs font-black uppercase tracking-wider text-slate-400">Final caption</p><div className="mt-3 whitespace-pre-wrap rounded-2xl bg-slate-50 p-5 text-sm leading-7 text-slate-700">{campaign.caption}</div>{campaign.media_items?.length>0?<div className="mt-4 grid gap-3 sm:grid-cols-2">{campaign.media_items.map((item,index)=><a key={item.id} href={item.url} target="_blank" className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-50">{item.content_type.startsWith("image/")?<img src={item.url} alt={"Proof media "+(index+1)} className="h-48 w-full object-contain bg-white"/>:<div className="grid h-48 place-items-center text-sm font-extrabold text-[#070a45]">Open video</div>}<div className="flex items-center justify-between gap-2 p-3 text-xs font-extrabold text-[#070a45]"><span>{campaign.media_items.length>1?"Carousel item "+(index+1):"Final media"}</span><ExternalLink size={14}/></div></a>)}</div>:campaign.media_url&&<a href={campaign.media_url} target="_blank" className="mt-4 inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-extrabold text-[#070a45]">Open final media <ExternalLink size={15}/></a>}{campaign.destination_url&&<a href={campaign.destination_url} target="_blank" className="ml-2 mt-4 inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-extrabold text-[#070a45]">Open destination <ExternalLink size={15}/></a>}</div></section>{campaign.proof_status==="pending_advertiser"&&<section className="rounded-[1.7rem] border border-slate-200 bg-white p-6"><h3 className="font-black text-[#070a45]">Your approval</h3><p className="mt-2 text-sm leading-6 text-slate-500">Approve only when the caption, media and destination above are correct. After approval, Meloli may schedule or publish the advert.</p><form onSubmit={e=>decide("changes_requested",e)} className="mt-5"><label className="block"><span className="mb-2 block text-xs font-black uppercase tracking-wider text-slate-500">Correction request</span><textarea value={feedback} onChange={e=>setFeedback(e.target.value)} className="min-h-28 w-full rounded-xl border border-slate-200 p-4 text-sm outline-none focus:border-[#070a45]" placeholder="Describe exactly what should change..."/></label><div className="mt-4 grid gap-3 sm:grid-cols-2"><button type="submit" disabled={busy!==""} className="flex h-12 items-center justify-center gap-2 rounded-xl border border-rose-200 text-sm font-extrabold text-rose-700 disabled:opacity-50"><MessageSquareWarning size={17}/>{busy==="changes_requested"?"Sending...":"Request changes"}</button><button type="button" onClick={()=>decide("approved")} disabled={busy!==""} className="flex h-12 items-center justify-center gap-2 rounded-xl bg-[#e31545] text-sm font-extrabold text-white disabled:opacity-50"><CheckCircle2 size={17}/>{busy==="approved"?"Approving...":"Approve final proof"}</button></div></form></section>}</div>}</div></main>;
}