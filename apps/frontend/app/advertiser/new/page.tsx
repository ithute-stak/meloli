"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ImagePlus, Loader2, Megaphone, UploadCloud } from "lucide-react";
import { API_URL, api, getSessionUser } from "@/lib/api";

type Package = { id:number; code:string; name:string; description:string; price:number; posts_included:number };
type Campaign = { id:number };
type MediaUpload = { filename:string; content_type:string; size:number; url:string };

export default function NewCampaign(){
  const router=useRouter();
  const [packages,setPackages]=useState<Package[]>([]);
  const [saving,setSaving]=useState(false);
  const [uploading,setUploading]=useState(false);
  const [media,setMedia]=useState<MediaUpload[]>([]);
  const [error,setError]=useState("");
  const [form,setForm]=useState({title:"",caption:"",package_code:"",preferred_publish_at:"",media_url:"",destination_url:""});

  useEffect(()=>{
    const user=getSessionUser();
    if(!user||user.role!=="advertiser"){router.replace("/login");return;}
    api<Package[]>("/api/v1/packages").then(data=>{setPackages(data);if(data[0])setForm(v=>({...v,package_code:data[0].code}));}).catch(e=>setError(e.message));
  },[router]);

  const change=(key:string,value:string)=>setForm(v=>({...v,[key]:value}));

  async function uploadFiles(files:File[]){
    if(files.length===0)return;
    const combinedTypes=[...media.map(m=>m.content_type),...files.map(f=>f.type)];
    if(media.length+files.length>10){setError("A campaign can contain at most 10 images, or one video.");return;}
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
      const campaign=await api<Campaign>("/api/v1/campaigns",{method:"POST",body:JSON.stringify({...form,preferred_publish_at:form.preferred_publish_at?new Date(form.preferred_publish_at).toISOString():null,media_url:form.media_url||null,media_items:media.map(m=>({url:m.url,content_type:m.content_type})),destination_url:form.destination_url||null})},true);
      router.push(`/advertiser/campaigns/${campaign.id}/payment`);
    }catch(err){setError(err instanceof Error?err.message:"Unable to create advert");}
    finally{setSaving(false);}
  }

  return <main className="min-h-screen bg-[#f5f6fa] p-4 sm:p-6 lg:p-8"><div className="mx-auto max-w-5xl">
    <div className="mb-6 flex items-center justify-between"><Link href="/advertiser" className="inline-flex items-center gap-2 text-sm font-extrabold text-slate-500"><ArrowLeft size={16}/> Back</Link><div className="font-black text-[#070a45]">MELOLI<span className="text-[#e31545]">AIRWAVES</span></div></div>
    <section className="rounded-[1.8rem] bg-[#070a45] p-6 text-white sm:p-8"><div className="flex gap-4"><div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white/10"><Megaphone/></div><div><p className="text-xs font-black uppercase tracking-[.2em] text-white/45">New campaign</p><h1 className="mt-2 text-3xl font-black">Create an advert</h1><p className="mt-2 text-sm text-white/60">Upload your artwork or video, write the caption and choose the package Meloli should review.</p></div></div></section>
    <form onSubmit={submit} className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">
      <section className="rounded-[1.5rem] border border-slate-200 bg-white p-5 sm:p-6"><h2 className="font-black text-[#070a45]">Advert details</h2><div className="mt-5 space-y-5"><Field label="Campaign title"><input value={form.title} onChange={e=>change("title",e.target.value)} required minLength={3} placeholder="October promotion"/></Field><Field label="Facebook caption"><textarea rows={8} value={form.caption} onChange={e=>change("caption",e.target.value)} required placeholder="Write the content Meloli should review..."/></Field>
      <div><div className="mb-2 flex items-center justify-between gap-3"><span className="text-sm font-bold text-slate-700">Artwork or video</span><span className="text-xs font-bold text-slate-400">{media.length}/10 media</span></div><label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50 p-7 text-center transition hover:border-[#e31545]/50"><input className="hidden" multiple type="file" accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime" onChange={e=>uploadFiles(Array.from(e.target.files||[]))}/><div className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-[#070a45] shadow-sm">{uploading?<Loader2 className="animate-spin"/>:<UploadCloud/>}</div><p className="mt-3 text-sm font-extrabold text-[#070a45]">{uploading?"Uploading media...":"Choose media"}</p><p className="mt-1 text-xs text-slate-400">Up to 10 images for a carousel, or one video · 25 MB per file</p></label>{media.length>0&&<div className="mt-3 grid gap-3 sm:grid-cols-2">{media.map((item,index)=><div key={item.filename} className="relative rounded-2xl border border-emerald-200 bg-emerald-50 p-3">{item.content_type.startsWith("image/")?<img src={API_URL+item.url} alt={"Advert media "+(index+1)} className="h-40 w-full rounded-xl bg-white object-contain"/>:<div className="grid h-40 place-items-center rounded-xl bg-white text-sm font-extrabold text-[#070a45]">Video ready</div>}<div className="mt-3 flex items-center justify-between gap-2"><div className="min-w-0"><p className="truncate text-xs font-extrabold text-emerald-800">{index===0?"Primary media":"Carousel item "+(index+1)}</p><p className="text-[11px] text-emerald-700/70">{(item.size/1024/1024).toFixed(2)} MB · {item.content_type}</p></div><button type="button" onClick={()=>removeMedia(index)} className="rounded-lg border border-rose-200 bg-white px-2.5 py-1.5 text-xs font-extrabold text-rose-700">Remove</button></div></div>)}</div>}</div>
      <Field label="Destination link"><input value={form.destination_url} onChange={e=>change("destination_url",e.target.value)} placeholder="Optional website or contact link"/></Field><Field label="Preferred publish date and time"><input type="datetime-local" value={form.preferred_publish_at} onChange={e=>change("preferred_publish_at",e.target.value)}/></Field></div></section>
      <aside className="space-y-5"><section className="rounded-[1.5rem] border border-slate-200 bg-white p-5"><h2 className="font-black text-[#070a45]">Choose package</h2><div className="mt-4 space-y-3">{packages.map(p=><button key={p.id} type="button" onClick={()=>change("package_code",p.code)} className={`w-full rounded-2xl border p-4 text-left ${form.package_code===p.code?"border-[#e31545] bg-rose-50":"border-slate-200"}`}><p className="font-black text-[#070a45]">{p.name}</p><p className="mt-1 text-xs leading-5 text-slate-500">{p.description}</p><p className="mt-3 text-lg font-black text-[#070a45]">M {Number(p.price).toFixed(2)}</p></button>)}</div></section>{error&&<div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}<button disabled={saving||uploading||!form.package_code} className="flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-[#e31545] font-extrabold text-white disabled:opacity-50">{saving&&<Loader2 size={18} className="animate-spin"/>}{saving?"Saving...":"Continue to payment"}</button></aside>
    </form>
  </div></main>;
}

function Field({label,children}:{label:string;children:React.ReactNode}){return <label className="block"><span className="mb-2 block text-sm font-bold text-slate-700">{label}</span><div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 focus-within:border-[#070a45] [&_input]:h-12 [&_input]:w-full [&_input]:bg-transparent [&_input]:text-sm [&_input]:outline-none [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:bg-transparent [&_textarea]:py-3 [&_textarea]:text-sm [&_textarea]:outline-none">{children}</div></label>}
