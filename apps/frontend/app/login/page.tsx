"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { ArrowLeft, Loader2, LockKeyhole, Mail, Megaphone } from "lucide-react";
import { API_URL, api, AuthResponse, saveSession } from "@/lib/api";

export default function LoginPage(){
  const router = useRouter();
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [otpCode,setOtpCode]=useState("");
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const [portalName,setPortalName]=useState("Meloli Airwaves");
  const [tenantSlug,setTenantSlug]=useState("");

  useEffect(()=>{
    const params=new URLSearchParams(window.location.search);
    const tenant=params.get("tenant");
    const resolveUrl=tenant
      ? API_URL+"/api/v1/tenants/resolve?slug="+encodeURIComponent(tenant)
      : (!["localhost","127.0.0.1"].includes(window.location.hostname)?API_URL+"/api/v1/tenants/resolve?host="+encodeURIComponent(window.location.hostname):"");
    if(resolveUrl)fetch(resolveUrl).then(r=>r.ok?r.json():null).then(data=>{if(data){setPortalName(data.name);setTenantSlug(data.slug)}}).catch(()=>undefined);
  },[]);

  async function submit(event:FormEvent){
    event.preventDefault(); setError(""); setLoading(true);
    try{
      const auth=await api<AuthResponse>("/api/v1/auth/login",{method:"POST",body:JSON.stringify({email,password,otp_code:otpCode||null})});
      saveSession(auth);
      router.push(auth.user.is_tenant_admin?"/dashboard":auth.user.role==="advertiser"?"/advertiser":"/dashboard");
    }catch(err){setError(err instanceof Error?err.message:"Unable to sign in");}
    finally{setLoading(false);}
  }

  return <main className="min-h-screen bg-[#f0f2f5] lg:grid lg:grid-cols-2">
    <section className="relative hidden overflow-hidden bg-[#0866ff] p-12 text-white lg:flex lg:flex-col lg:justify-between">
      <div className="absolute -right-20 top-20 h-80 w-80 rounded-full bg-[#0866ff]/20 blur-3xl"/>
      <Link href="/" className="relative flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-xl bg-white/10"><Megaphone/></div><div><div className="font-bold tracking-tight">{portalName}</div><div className="text-[10px] tracking-normal text-white/50">Advertising Portal</div></div></Link>
      <div className="relative max-w-xl"><p className="text-sm font-bold tracking-normal text-white/50">Campaign management</p><h1 className="mt-4 text-4xl font-bold leading-tight tracking-tight">A professional bridge between advertisers and {portalName}.</h1><p className="mt-5 max-w-lg text-lg leading-8 text-white/65">Submit content, manage approvals, follow publishing schedules and keep the full campaign history in one secure workspace.</p></div>
      <p className="relative text-sm text-white/40">Advertising management for {portalName}.</p>
    </section>
    <section className="flex min-h-screen items-center justify-center p-5 sm:p-8">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 inline-flex items-center gap-2 text-sm font-bold text-slate-500 lg:hidden"><ArrowLeft size={16}/> Back home</Link>
        <div className="mb-8 lg:hidden"><div className="text-2xl font-bold tracking-tight"><span className="text-slate-900">{portalName}</span><span className="hidden"></span></div><p className="mt-1 text-xs font-bold tracking-normal text-slate-400">Advertising Portal</p></div>
        <h2 className="text-2xl font-bold tracking-tight text-slate-900">Welcome back</h2><p className="mt-2 text-slate-500">Sign in to manage your adverts and approvals.</p>
        <form className="mt-8 space-y-5" onSubmit={submit}>
          <label className="block"><span className="mb-2 block text-sm font-bold text-slate-700">Email address</span><div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 shadow-sm focus-within:border-[#0866ff]"><Mail size={18} className="text-slate-400"/><input className="h-14 w-full outline-none" type="email" placeholder="you@example.com" value={email} onChange={e=>setEmail(e.target.value)} required/></div></label>
          <label className="block"><div className="mb-2 flex items-center justify-between"><span className="text-sm font-bold text-slate-700">Password</span><Link href="/forgot-password" className="text-xs font-semibold text-[#0866ff]">Forgot password?</Link></div><div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 shadow-sm focus-within:border-[#0866ff]"><LockKeyhole size={18} className="text-slate-400"/><input className="h-14 w-full outline-none" type="password" placeholder="••••••••" value={password} onChange={e=>setPassword(e.target.value)} required/></div></label>
          <label className="block"><div className="mb-2 flex items-center justify-between"><span className="text-sm font-bold text-slate-700">Authenticator code</span><span className="text-xs font-bold text-slate-400">Staff 2FA only</span></div><div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 shadow-sm focus-within:border-[#0866ff]"><LockKeyhole size={18} className="text-slate-400"/><input className="h-14 w-full tracking-[.25em] outline-none" inputMode="numeric" autoComplete="one-time-code" placeholder="000000" value={otpCode} onChange={e=>setOtpCode(e.target.value.replace(/\D/g,"").slice(0,8))}/></div></label>
          {error&&<div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">{error}</div>}
          <button disabled={loading} className="flex h-14 w-full items-center justify-center gap-2 rounded-xl bg-[#0866ff] font-semibold text-white shadow-lg shadow-indigo-950/20 disabled:opacity-60">{loading&&<Loader2 size={18} className="animate-spin"/>}{loading?"Signing in...":"Sign in"}</button>
        </form>
        <div className="my-7 flex items-center gap-3"><div className="h-px flex-1 bg-slate-200"/><span className="text-xs font-bold uppercase tracking-widest text-slate-400">New advertiser?</span><div className="h-px flex-1 bg-slate-200"/></div>
        <Link href={tenantSlug?"/register?tenant="+tenantSlug:"/register"} className="grid h-14 w-full place-items-center rounded-xl border border-slate-200 bg-white font-semibold text-slate-900">Create advertiser account</Link>
      </div>
    </section>
  </main>
}
