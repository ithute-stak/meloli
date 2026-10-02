"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ImagePlus, Loader2, Megaphone, UploadCloud } from "lucide-react";
import { API_URL, api, getSessionUser } from "@/lib/api";

type Package = { id:number; code:string; name:string; description:string; price:number; posts_included:number; max_media_items:number; allow_video:boolean; allow_carousel:boolean };
type Campaign = { id:number };
type MediaUpload = { filename:string; content_type:string; size:number; url:string };

export default function NewCampaign(){
  const router=useRouter();
  const [packages,setPackages]=useState<Package[]>([]);
  const [saving,setSaving]=useState(false);
  const [uploading,setUploading]=useState(false);
  const [media,setMedia]=useState<MediaUpload[]>([]);
  const [error,setError]=useState("");
  const [form,setForm]=useState({title:"",caption:"",package_code:"",engagement_mode:"normal",competition_closes_at:"",competition_auto_certify:false,preferred_publish_at:"",media_url:"",destination_url:""});

  useEffect(()=>{
    const user=getSessionUser();
    if(!user||user.role!=="advertiser"){router.replace("/login");return;}
    api<Package[]>("/api/v1/packages",{},true).then(data=>{setPackages(data);if(data[0])setForm(v=>({...v,package_code:data[0].code}));}).catch(e=>setError(e.message));
  },[router]);

  const change=(key:string,value:string|boolean)=>setForm(v=>({...v,[key]:value}));
  const selectedPackage=packages.find(p=>p.code===form.package_code);

  async function uploadFiles(files:File[]){
    if(files.length===0)return;
    const combinedTypes=[...media.map(m=>m.content_type),...files.map(f=>f.type)];
    const maxMedia=selectedPackage?.max_media_items||10;
    if(media.length+files.length>maxMedia){setError((selectedPackage?.name||"This package")+" allows at most "+maxMedia+" media item(s).");return;}
    if(combinedTypes.some(t=>t.startsWith("video/"))&&!selectedPackage?.allow_video){setError((selectedPackage?.name||"This package")+" does not allow video adverts.");return;}
    if(combinedTypes.length>1&&!selectedPackage?.allow_carousel){setError((selectedPackage?.name||"This package")+" does not allow carousel adverts.");return;}
    if(combinedTypes.length>1&&combinedTypes.some(t=>t.startsWith("video/"))){setError("Video adverts support one video only. Multi-media carousel campaigns must contain images only.");return;}
    setUploading(true);setError("");
    try{
      const uploaded:MediaUpload[]=[];
      for(const file of files){
        const data=new FormData();data.append("file",file);
        uploaded.push(await api<MediaUpload>("/api/v1/media",{method:"POST",body:data},true));
      }
      const next=[...media,...uploaded];
      setMedia(next);change("media_url",next[0]?.url||"");
    }catch(err){setError(err instanceof Error?err.message:"Unable to upload media");}
    finally{setUploading(false);}
  }
  function removeMedia(index:number){
    setMedia(current=>{
      const next=current.filter((_,i)=>i!==index);
      change("media_url",next[0]?.url||"");
      return next;
    });
  }

  async function submit(e:FormEvent){
    e.preventDefault(); setError(""); setSaving(true);
    try{
      const campaign=await api<Campaign>("/api/v1/campaigns",{method:"POST",body:JSON.stringify({...form,competition_closes_at:form.engagement_mode==="competition_one_comment"&&form.competition_closes_at?new Date(form.competition_closes_at).toISOString():null,competition_auto_certify:form.engagement_mode==="competition_one_comment"?form.competition_auto_certify:false,preferred_publish_at:form.preferred_publish_at?new Date(form.preferred_publish_at).toISOString():null,media_url:form.media_url||null,media_items:media.map(m=>({url:m.url,content_type:m.content_type})),destination_url:form.destination_url||null})},true);
      router.push(`/advertiser/campaigns/${campaign.id}/payment`);
    }catch(err){setError(err instanceof Error?err.message:"Unable to create advert");}
    finally{setSaving(false);}
  }

  return <main className="min-h-screen bg-[#f0f2f5] p-4 sm:p-6 lg:p-8"><div className="mx-auto max-w-5xl">
    <div className="mb-6 flex items-center justify-between"><Link href="/advertiser" className="inline-flex items-center gap-2 text-sm font-semibold text-slate-500"><ArrowLeft size={16}/> Back</Link><div className="font-bold text-slate-900">MELOLI<span className="text-[#0866ff]">AIRWAVES</span></div></div>
    <section className="rounded-xl bg-[#0866ff] p-6 text-white sm:p-8"><div className="flex gap-4"><div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-white/10"><Megaphone/></div><div><p className="text-xs font-bold tracking-normal text-white/45">New campaign</p><h1 className="mt-2 text-2xl font-bold">Create an advert</h1><p className="mt-2 text-sm text-white/60">Upload your artwork or video, write the caption and choose the package the Page team should review.</p></div></div></section>
    <form onSubmit={submit} className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">
      <section className="rounded-xl border border-slate-200 bg-white p-5 sm:p-6"><h2 className="font-bold text-slate-900">Advert details</h2><div className="mt-5 space-y-5"><Field label="Campaign title"><input value={form.title} onChange={e=>change("title",e.target.value)} required minLength={3} placeholder="October promotion"/></Field><Field label="Facebook caption"><textarea rows={8} value={form.caption} onChange={e=>change("caption",e.target.value)} required placeholder="Write the content the Page team should review..."/></Field><div><span className="mb-2 block text-sm font-bold text-slate-700">Campaign engagement mode</span><div className="grid gap-3 sm:grid-cols-2"><button type="button" onClick={()=>change("engagement_mode","normal")} className={"rounded-xl border p-4 text-left "+(form.engagement_mode==="normal"?"border-[#0866ff] bg-indigo-50":"border-slate-200 bg-white")}><p className="font-bold text-slate-900">Normal engagement</p><p className="mt-1 text-xs leading-5 text-slate-500">Use ordinary Facebook reactions, comments and performance metrics.</p></button><button type="button" onClick={()=>change("engagement_mode","competition_one_comment")} className={"rounded-xl border p-4 text-left "+(form.engagement_mode==="competition_one_comment"?"border-[#e31545] bg-rose-50":"border-slate-200 bg-white")}><p className="font-bold text-slate-900">Competition voting</p><p className="mt-1 text-xs leading-5 text-slate-500">One person may like one comment only. If the same person likes two or more comments, all of that person's votes become invalid.</p></button></div></div>{form.engagement_mode==="competition_one_comment"&&<div className="rounded-xl border border-blue-200 bg-[#e7f3ff] p-4"><p className="font-bold text-slate-900">Competition automation</p><p className="mt-1 text-xs leading-5 text-[#65676b]">Set a closing time so the platform can perform a final reaction sync automatically. Certification will only run when the tenant plan supports certified competitions.</p><div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end"><Field label="Competition closes at"><input type="datetime-local" value={form.competition_closes_at} onChange={e=>change("competition_closes_at",e.target.value)}/></Field><label className="flex h-12 items-center gap-3 rounded-xl border border-blue-200 bg-white px-4 text-sm font-semibold text-slate-700"><input type="checkbox" checked={form.competition_auto_certify} onChange={e=>change("competition_auto_certify",e.target.checked)} className="h-4 w-4"/> Auto-certify final result</label></div></div>}
      <div><div className="mb-2 flex items-center justify-between gap-3"><span className="text-sm font-bold text-slate-700">Artwork or video</span><span className="text-xs font-bold text-slate-400">{media.length}/{selectedPackage?.max_media_items||10} media</span></div><label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 p-7 text-center transition hover:border-[#e31545]/50"><input className="hidden" multiple type="file" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime" onChange={e=>uploadFiles(Array.from(e.target.files||[]))}/><div className="grid h-12 w-12 place-items-center rounded-xl bg-white text-slate-900 shadow-sm">{uploading?<Loader2 className="animate-spin"/>:<UploadCloud/>}</div><p className="mt-3 text-sm font-semibold text-slate-900">{uploading?"Uploading media...":"Choose media"}</p><p className="mt-1 text-xs text-slate-400">{selectedPackage?.allow_carousel?"Up to "+(selectedPackage?.max_media_items||10)+" images for a carousel":"Single-media adverts only"}{selectedPackage?.allow_video?" · video allowed":" · image only"} · 25 MB per file</p></label>{media.length>0&&<div className="mt-3 grid gap-3 sm:grid-cols-2">{media.map((item,index)=><div key={item.filename} className="relative rounded-xl border border-emerald-200 bg-emerald-50 p-3">{item.content_type.startsWith("image/")?<img src={API_URL+item.url} alt={"Advert media "+(index+1)} className="h-40 w-full rounded-xl bg-white object-contain"/>:<div className="grid h-40 place-items-center rounded-xl bg-white text-sm font-semibold text-slate-900">Video ready</div>}<div className="mt-3 flex items-center justify-between gap-2"><div className="min-w-0"><p className="truncate text-xs font-semibold text-emerald-800">{index===0?"Primary media":"Carousel item "+(index+1)}</p><p className="text-[11px] text-emerald-700/70">{(item.size/1024/1024).toFixed(2)} MB · {item.content_type}</p></div><button type="button" onClick={()=>removeMedia(index)} className="rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-rose-700">Remove</button></div></div>)}</div>}</div>
      <Field label="Destination link"><input value={form.destination_url} onChange={e=>change("destination_url",e.target.value)} placeholder="Optional website or contact link"/></Field><Field label="Preferred publish date and time"><input type="datetime-local" value={form.preferred_publish_at} onChange={e=>change("preferred_publish_at",e.target.value)}/></Field></div></section>
      <aside className="space-y-5"><section className="rounded-xl border border-slate-200 bg-white p-5"><h2 className="font-bold text-slate-900">Choose package</h2><div className="mt-4 space-y-3">{packages.map(p=><button key={p.id} type="button" onClick={()=>change("package_code",p.code)} className={`w-full rounded-xl border p-4 text-left ${form.package_code===p.code?"border-[#e31545] bg-rose-50":"border-slate-200"}`}><p className="font-bold text-slate-900">{p.name}</p><p className="mt-1 text-xs leading-5 text-slate-500">{p.description}</p><p className="mt-3 text-lg font-bold text-slate-900">M {Number(p.price).toFixed(2)}</p><p className="mt-2 text-[11px] font-bold text-slate-400">Up to {p.max_media_items} media · {p.allow_video?"video":"image only"} · {p.allow_carousel?"carousel":"single media"}</p></button>)}</div></section>{error&&<div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}<button disabled={saving||uploading||!form.package_code} className="flex h-14 w-full items-center justify-center gap-2 rounded-xl bg-[#0866ff] font-semibold text-white disabled:opacity-50">{saving&&<Loader2 size={18} className="animate-spin"/>}{saving?"Saving...":"Continue to payment"}</button></aside>
    </form>
  </div></main>;
}

function Field({label,children}:{label:string;children:React.ReactNode}){return <label className="block"><span className="mb-2 block text-sm font-bold text-slate-700">{label}</span><div className="rounded-xl border border-slate-200 bg-slate-50 px-4 focus-within:border-[#0866ff] [&_input]:h-12 [&_input]:w-full [&_input]:bg-transparent [&_input]:text-sm [&_input]:outline-none [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:bg-transparent [&_textarea]:py-3 [&_textarea]:text-sm [&_textarea]:outline-none">{children}</div></label>}
