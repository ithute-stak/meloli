"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ArrowRight, Loader2, Megaphone, ShieldCheck } from "lucide-react";
import { API_URL } from "@/lib/api";

type Tenant={id:number;name:string;slug:string;facebook_page_name?:string|null;logo_url?:string|null;accent_color:string;generated_url:string};

export default function TenantPortal(){
  const {slug}=useParams<{slug:string}>();
  const [tenant,setTenant]=useState<Tenant|null>(null); const [error,setError]=useState("");
  useEffect(()=>{fetch(API_URL+"/api/v1/tenants/resolve?slug="+encodeURIComponent(slug)).then(async r=>{if(!r.ok)throw new Error((await r.json()).detail||"Portal not found");return r.json()}).then(setTenant).catch(e=>setError(e.message));},[slug]);
  if(error)return <main className="grid min-h-screen place-items-center bg-[#f5f6fa] p-5"><div className="rounded-2xl bg-white p-8 text-center shadow"><h1 className="text-2xl font-black text-[#070a45]">Portal not found</h1><p className="mt-2 text-sm text-slate-500">{error}</p></div></main>;
  if(!tenant)return <main className="grid min-h-screen place-items-center bg-[#f5f6fa]"><Loader2 className="animate-spin text-[#e31545]"/></main>;
  const accent=tenant.accent_color||"#e31545";
  return <main className="min-h-screen bg-white text-slate-950">
    <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8"><div className="flex items-center gap-3">{tenant.logo_url?<img src={tenant.logo_url.startsWith("http")?tenant.logo_url:API_URL+tenant.logo_url} alt={tenant.name} className="h-11 w-11 rounded-xl object-contain"/>:<div className="grid h-11 w-11 place-items-center rounded-2xl bg-[#070a45] text-white"><Megaphone size={20}/></div>}<div><p className="text-lg font-black text-[#070a45]">{tenant.name}</p><p className="text-[10px] font-bold uppercase tracking-[.18em] text-slate-400">Advertising Portal</p></div></div><Link href={"/login?tenant="+tenant.slug} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-extrabold text-[#070a45]">Sign in</Link></div></header>
    <section className="relative overflow-hidden bg-[#f7f8fc]"><div className="mx-auto grid max-w-7xl items-center gap-10 px-4 py-20 sm:px-6 lg:grid-cols-[1.05fr_.95fr] lg:px-8 lg:py-28"><div><p className="text-xs font-black uppercase tracking-[.2em]" style={{color:accent}}>Advertise with {tenant.facebook_page_name||tenant.name}</p><h1 className="mt-4 max-w-3xl text-5xl font-black leading-[.98] tracking-[-.04em] text-[#070a45] sm:text-6xl">Submit, approve and track your advert from one portal.</h1><p className="mt-6 max-w-xl text-lg leading-8 text-slate-600">Create your campaign, upload media, manage payment, approve the final proof and follow publication performance without sharing Facebook credentials.</p><div className="mt-8 flex flex-col gap-3 sm:flex-row"><Link href={"/register?tenant="+tenant.slug} className="inline-flex items-center justify-center gap-2 rounded-2xl px-6 py-4 font-extrabold text-white" style={{backgroundColor:accent}}>Create advertiser account <ArrowRight size={18}/></Link><Link href={"/login?tenant="+tenant.slug} className="inline-flex items-center justify-center rounded-2xl border border-slate-200 bg-white px-6 py-4 font-extrabold text-[#070a45]">Open portal</Link></div></div><div className="rounded-[2rem] bg-[#070a45] p-6 text-white shadow-2xl"><div className="grid h-14 w-14 place-items-center rounded-2xl bg-white/10"><ShieldCheck/></div><h2 className="mt-6 text-2xl font-black">Controlled publishing</h2><p className="mt-3 leading-7 text-white/60">Every campaign follows the Page owner’s review, final-proof and publishing workflow. Competition campaigns can also enforce one person, one valid comment vote.</p><div className="mt-6 grid gap-3 sm:grid-cols-2"><Stat label="Mobile ready" value="Yes"/><Stat label="Final proof" value="Required"/><Stat label="Campaign history" value="Tracked"/><Stat label="Competition mode" value="Optional"/></div></div></div></section>
  </main>
}
function Stat({label,value}:{label:string;value:string}){return <div className="rounded-2xl bg-white/10 p-4"><p className="text-xs text-white/50">{label}</p><p className="mt-2 font-black">{value}</p></div>}
