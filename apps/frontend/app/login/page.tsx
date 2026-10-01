import Link from "next/link";
import { ArrowLeft, LockKeyhole, Mail, Megaphone } from "lucide-react";

export default function LoginPage(){
  return <main className="min-h-screen bg-[#f5f6fa] lg:grid lg:grid-cols-2">
    <section className="relative hidden overflow-hidden bg-[#070a45] p-12 text-white lg:flex lg:flex-col lg:justify-between">
      <div className="absolute -right-20 top-20 h-80 w-80 rounded-full bg-[#e31545]/20 blur-3xl"/>
      <Link href="/" className="relative flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-2xl bg-white/10"><Megaphone/></div><div><div className="font-black tracking-tight">MELOLI<span className="text-[#ff315d]">AIRWAVES</span></div><div className="text-[10px] uppercase tracking-[.2em] text-white/50">Advertising Portal</div></div></Link>
      <div className="relative max-w-xl"><p className="text-sm font-bold uppercase tracking-[.2em] text-white/50">Campaign management</p><h1 className="mt-4 text-5xl font-black leading-tight tracking-tight">A professional bridge between advertisers and Meloli Airwaves.</h1><p className="mt-5 max-w-lg text-lg leading-8 text-white/65">Submit content, manage approvals, follow publishing schedules and keep the full campaign history in one secure workspace.</p></div>
      <p className="relative text-sm text-white/40">The Online Media Everyone is Following.</p>
    </section>
    <section className="flex min-h-screen items-center justify-center p-5 sm:p-8">
      <div className="w-full max-w-md">
        <Link href="/" className="mb-8 inline-flex items-center gap-2 text-sm font-bold text-slate-500 lg:hidden"><ArrowLeft size={16}/> Back home</Link>
        <div className="mb-8 lg:hidden"><div className="text-2xl font-black tracking-tight"><span className="text-[#070a45]">MELOLI</span><span className="text-[#e31545]">AIRWAVES</span></div><p className="mt-1 text-xs font-bold uppercase tracking-[.18em] text-slate-400">Advertising Portal</p></div>
        <h2 className="text-3xl font-black tracking-tight text-[#070a45]">Welcome back</h2><p className="mt-2 text-slate-500">Sign in to manage your adverts and approvals.</p>
        <form className="mt-8 space-y-5" action="/dashboard">
          <label className="block"><span className="mb-2 block text-sm font-bold text-slate-700">Email address</span><div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 shadow-sm focus-within:border-[#070a45]"><Mail size={18} className="text-slate-400"/><input className="h-14 w-full outline-none" type="email" placeholder="you@example.com" required/></div></label>
          <label className="block"><div className="mb-2 flex items-center justify-between"><span className="text-sm font-bold text-slate-700">Password</span><a href="#" className="text-xs font-bold text-[#e31545]">Forgot password?</a></div><div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white px-4 shadow-sm focus-within:border-[#070a45]"><LockKeyhole size={18} className="text-slate-400"/><input className="h-14 w-full outline-none" type="password" placeholder="••••••••" required/></div></label>
          <button className="h-14 w-full rounded-2xl bg-[#070a45] font-extrabold text-white shadow-lg shadow-indigo-950/20">Sign in</button>
        </form>
        <div className="my-7 flex items-center gap-3"><div className="h-px flex-1 bg-slate-200"/><span className="text-xs font-bold uppercase tracking-widest text-slate-400">New advertiser?</span><div className="h-px flex-1 bg-slate-200"/></div>
        <button className="h-14 w-full rounded-2xl border border-slate-200 bg-white font-extrabold text-[#070a45]">Create advertiser account</button>
      </div>
    </section>
  </main>
}
