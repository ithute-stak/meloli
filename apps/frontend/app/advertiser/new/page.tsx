"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Megaphone } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";

type Package = { id:number; code:string; name:string; description:string; price:number; posts_included:number };
type Campaign = { id:number };

export default function NewCampaign(){
  const router=useRouter();
  const [packages,setPackages]=useState<Package[]>([]);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [form,setForm]=useState({title:"",caption:"",package_code:"",preferred_publish_at:"",media_url:"",destination_url:""});

  useEffect(()=>{
    const user=getSessionUser();
    if(!user||user.role!=="advertiser"){router.replace("/login");return;}
    api<Package[]>("/api/v1/packages").then(data=>{setPackages(data);if(data[0])setForm(v=>({...v,package_code:data[0].code}));}).catch(e=>setError(e.message));
  },[router]);

  const change=(key:string,value:string)=>setForm(v=>({...v,[key]:value}));

  async function submit(e:FormEvent){
    e.preventDefault(); setError(""); setSaving(true);
    try{
      const campaign=await api<Campaign>("/api/v1/campaigns",{method:"POST",body:JSON.stringify({...form,preferred_publish_at:form.preferred_publish_at?new Date(form.preferred_publish_at).toISOString():null,media_url:form.media_url||null,destination_url:form.destination_url||null})},true);
      router.push(`/advertiser/campaigns/${campaign.id}/payment`);
    }catch(err){setError(err instanceof Error?err.message:"Unable to create advert");}
    finally{setSaving(false);}
  }

  return <main className="min-h-screen bg-[#f5f6fa] p-4 sm:p-6 lg:p-8"><div className="mx-auto max-w-5xl">
    <div className="mb-6 flex items-center justify-between"><Link href="/advertiser" className="inline-flex items-center gap-2 text-sm font-extrabold text-slate-500"><ArrowLeft size={16}/> Back</Link><div className="font-black text-[#070a45]">MELOLI<span className="text-[#e31545]">AIRWAVES</span></div></div>
    <section className="rounded-[1.8rem] bg-[#070a45] p-6 text-white sm:p-8"><div className="flex gap-4"><div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white/10"><Megaphone/></div><div><p className="text-xs font-black uppercase tracking-[.2em] text-white/45">New campaign</p><h1 className="mt-2 text-3xl font-black">Create an advert</h1><p className="mt-2 text-sm text-white/60">Prepare the advert for Meloli review and choose the package you want to purchase.</p></div></div></section>
    <form onSubmit={submit} className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">
      <section className="rounded-[1.5rem] border border-slate-200 bg-white p-5 sm:p-6"><h2 className="font-black text-[#070a45]">Advert details</h2><div className="mt-5 space-y-5"><Field label="Campaign title"><input value={form.title} onChange={e=>change("title",e.target.value)} required minLength={3} placeholder="October promotion"/></Field><Field label="Facebook caption"><textarea rows={8} value={form.caption} onChange={e=>change("caption",e.target.value)} required placeholder="Write the content Meloli should review..."/></Field><Field label="Artwork or media URL"><input value={form.media_url} onChange={e=>change("media_url",e.target.value)} placeholder="https://..."/></Field><Field label="Destination link"><input value={form.destination_url} onChange={e=>change("destination_url",e.target.value)} placeholder="Optional"/></Field><Field label="Preferred publish date and time"><input type="datetime-local" value={form.preferred_publish_at} onChange={e=>change("preferred_publish_at",e.target.value)}/></Field></div></section>
      <aside className="space-y-5"><section className="rounded-[1.5rem] border border-slate-200 bg-white p-5"><h2 className="font-black text-[#070a45]">Choose package</h2><div className="mt-4 space-y-3">{packages.map(p=><button key={p.id} type="button" onClick={()=>change("package_code",p.code)} className={`w-full rounded-2xl border p-4 text-left ${form.package_code===p.code?"border-[#e31545] bg-rose-50":"border-slate-200"}`}><p className="font-black text-[#070a45]">{p.name}</p><p className="mt-1 text-xs leading-5 text-slate-500">{p.description}</p><p className="mt-3 text-lg font-black text-[#070a45]">M {Number(p.price).toFixed(2)}</p></button>)}</div></section>{error&&<div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}<button disabled={saving||!form.package_code} className="flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-[#e31545] font-extrabold text-white disabled:opacity-50">{saving&&<Loader2 size={18} className="animate-spin"/>}{saving?"Saving...":"Continue to payment"}</button></aside>
    </form>
  </div></main>;
}

function Field({label,children}:{label:string;children:React.ReactNode}){return <label className="block"><span className="mb-2 block text-sm font-bold text-slate-700">{label}</span><div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 focus-within:border-[#070a45] [&_input]:h-12 [&_input]:w-full [&_input]:bg-transparent [&_input]:text-sm [&_input]:outline-none [&_textarea]:w-full [&_textarea]:resize-y [&_textarea]:bg-transparent [&_textarea]:py-3 [&_textarea]:text-sm [&_textarea]:outline-none">{children}</div></label>}
