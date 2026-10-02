"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, BadgePercent, Building2, Loader2, LockKeyhole, Mail, Phone, UserRound } from "lucide-react";
import { api, AuthResponse, saveSession } from "@/lib/api";

export default function RegisterPage(){
  const router=useRouter();
  const [form,setForm]=useState({full_name:"",business_name:"",email:"",phone:"",password:"",referral_code:""});
  const [error,setError]=useState(""); const [loading,setLoading]=useState(false);
  const update=(key:string,value:string)=>setForm(v=>({...v,[key]:value}));
  async function submit(e:FormEvent){
    e.preventDefault();setError("");setLoading(true);
    try{
      const auth=await api<AuthResponse>("/api/v1/auth/register",{method:"POST",body:JSON.stringify(form)});
      saveSession(auth);router.push("/advertiser");
    }catch(err){setError(err instanceof Error?err.message:"Unable to create account");}
    finally{setLoading(false);}
  }
  return <main className="min-h-screen bg-[#f5f6fa] p-4 sm:p-6 lg:p-10">
    <div className="mx-auto grid min-h-[calc(100vh-2rem)] max-w-6xl overflow-hidden rounded-[2rem] bg-white shadow-2xl shadow-slate-300/30 lg:grid-cols-[.9fr_1.1fr]">
      <section className="relative overflow-hidden bg-[#070a45] p-8 text-white sm:p-10 lg:p-12">
        <div className="absolute -left-24 top-28 h-72 w-72 rounded-full bg-[#e31545]/20 blur-3xl"/>
        <Link href="/" className="relative inline-flex items-center gap-2 text-sm font-bold text-white/70"><ArrowLeft size={16}/> Back to Meloli</Link>
        <div className="relative mt-20 max-w-md"><p className="text-xs font-black uppercase tracking-[.2em] text-[#ff6c8f]">Advertiser onboarding</p><h1 className="mt-4 text-4xl font-black leading-tight sm:text-5xl">Your adverts. Your history. One professional workspace.</h1><p className="mt-5 leading-7 text-white/60">Create your account once, then submit campaigns, follow approvals, track payments and see when your content is published.</p></div>
      </section>
      <section className="p-6 sm:p-10 lg:p-12"><div className="mx-auto max-w-xl"><div className="mb-8"><p className="text-xs font-black uppercase tracking-[.18em] text-[#e31545]">Create account</p><h2 className="mt-2 text-3xl font-black text-[#070a45]">Join the Meloli advertiser portal</h2><p className="mt-2 text-sm leading-6 text-slate-500">Business name is optional, so individuals can advertise too.</p></div>
        <form className="grid gap-5 sm:grid-cols-2" onSubmit={submit}>
          <Field icon={<UserRound/>} label="Full name"><input value={form.full_name} onChange={e=>update("full_name",e.target.value)} required placeholder="Your full name"/></Field>
          <Field icon={<Building2/>} label="Business / organisation"><input value={form.business_name} onChange={e=>update("business_name",e.target.value)} placeholder="Optional"/></Field>
          <div className="sm:col-span-2"><Field icon={<Mail/>} label="Email address"><input type="email" value={form.email} onChange={e=>update("email",e.target.value)} required placeholder="you@example.com"/></Field></div>
          <Field icon={<Phone/>} label="Phone number"><input value={form.phone} onChange={e=>update("phone",e.target.value)} placeholder="+266 ..."/></Field>
          <Field icon={<BadgePercent/>} label="Referral / partner code"><input value={form.referral_code} onChange={e=>update("referral_code",e.target.value.toUpperCase())} placeholder="Optional"/></Field>
          <div className="sm:col-span-2"><Field icon={<LockKeyhole/>} label="Password"><input type="password" minLength={8} value={form.password} onChange={e=>update("password",e.target.value)} required placeholder="At least 8 characters"/></Field></div>
          {error&&<div className="sm:col-span-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">{error}</div>}
          <button disabled={loading} className="sm:col-span-2 flex h-14 items-center justify-center gap-2 rounded-2xl bg-[#e31545] font-extrabold text-white shadow-lg shadow-rose-200 disabled:opacity-60">{loading&&<Loader2 className="animate-spin" size={18}/>} {loading?"Creating account...":"Create advertiser account"}</button>
        </form>
        <p className="mt-6 text-center text-sm text-slate-500">Already registered? <Link href="/login" className="font-extrabold text-[#070a45]">Sign in</Link></p>
      </div></section>
    </div>
  </main>
}

function Field({icon,label,children}:{icon:React.ReactNode;label:string;children:React.ReactNode}){return <label className="block"><span className="mb-2 block text-sm font-bold text-slate-700">{label}</span><div className="flex h-14 items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 focus-within:border-[#070a45] focus-within:bg-white"><span className="text-slate-400 [&>svg]:h-[18px] [&>svg]:w-[18px]">{icon}</span><div className="min-w-0 flex-1 [&>input]:h-12 [&>input]:w-full [&>input]:bg-transparent [&>input]:text-sm [&>input]:outline-none">{children}</div></div></label>}
