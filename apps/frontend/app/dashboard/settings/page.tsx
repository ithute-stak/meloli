"use client";

import Link from "next/link";
import { ArrowLeft, CheckCircle2, Eye, EyeOff, Facebook, KeyRound, LockKeyhole, Save, Settings2, ShieldCheck } from "lucide-react";
import { useState } from "react";

export default function SettingsPage() {
  const [showSecrets, setShowSecrets] = useState(false);
  const [saved, setSaved] = useState(false);

  function save() {
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2200);
  }

  return <main className="min-h-screen bg-[#f5f6fa] text-slate-900">
    <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl">
      <div className="mx-auto flex h-20 max-w-[1500px] items-center gap-4 px-4 sm:px-6 lg:px-8">
        <Link href="/dashboard" className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 text-[#070a45]"><ArrowLeft size={18}/></Link>
        <div className="min-w-0 flex-1"><h1 className="truncate text-lg font-black text-[#070a45]">System Configuration</h1><p className="hidden text-xs text-slate-500 sm:block">Manage publishing integrations and protected platform credentials</p></div>
        <button onClick={save} className="flex items-center gap-2 rounded-xl bg-[#e31545] px-4 py-3 text-sm font-extrabold text-white"><Save size={17}/><span className="hidden sm:inline">Save changes</span></button>
      </div>
    </header>

    <div className="mx-auto grid max-w-[1500px] gap-6 p-4 sm:p-6 lg:grid-cols-[270px_1fr] lg:p-8">
      <aside className="h-fit rounded-[1.5rem] border border-slate-200 bg-white p-3">
        <button className="flex w-full items-center gap-3 rounded-xl bg-[#070a45] px-4 py-3 text-left text-sm font-extrabold text-white"><Facebook size={18}/> Facebook / Meta</button>
        <button className="mt-1 flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-bold text-slate-500 hover:bg-slate-50"><Settings2 size={18}/> General settings</button>
        <button className="mt-1 flex w-full items-center gap-3 rounded-xl px-4 py-3 text-left text-sm font-bold text-slate-500 hover:bg-slate-50"><ShieldCheck size={18}/> Security & audit</button>
      </aside>

      <section className="space-y-6">
        <div className="rounded-[1.75rem] bg-[#070a45] p-6 text-white sm:p-8">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-xs font-black uppercase tracking-[.2em] text-white/50">Publishing integration</p><h2 className="mt-2 text-3xl font-black tracking-tight">Facebook Page connection</h2><p className="mt-3 max-w-2xl text-sm leading-6 text-white/60">Credentials entered here are handled by the backend. Secret values are write-only and are never displayed again after saving.</p></div><div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs font-extrabold text-white/70"><span className="h-2.5 w-2.5 rounded-full bg-amber-400"/> Not connected</div></div>
        </div>

        <div className="rounded-[1.6rem] border border-slate-200 bg-white p-5 sm:p-7">
          <div className="mb-6 flex items-start gap-4"><div className="grid h-12 w-12 place-items-center rounded-2xl bg-blue-50 text-blue-600"><Facebook size={22}/></div><div><h3 className="font-black text-[#070a45]">Meta application credentials</h3><p className="mt-1 text-sm leading-6 text-slate-500">Configure the Meta app and Meloli Airwaves Page used for approved publishing.</p></div></div>

          <div className="grid gap-5 md:grid-cols-2">
            <Field label="Meta App ID" placeholder="Enter Meta App ID" />
            <SecretField label="Meta App Secret" placeholder="Enter new app secret" show={showSecrets}/>
            <Field label="Facebook Page ID" placeholder="Enter Meloli Page ID" />
            <Field label="Graph API version" placeholder="e.g. vXX.X" />
            <div className="md:col-span-2"><SecretField label="Page access token" placeholder="Enter or replace Page access token" show={showSecrets}/></div>
            <SecretField label="Webhook verify token" placeholder="Create a secure verify token" show={showSecrets}/>
            <Field label="Webhook callback URL" placeholder="https://your-domain/api/v1/meta/webhook" />
          </div>

          <div className="mt-6 flex flex-col gap-3 border-t border-slate-100 pt-6 sm:flex-row sm:items-center sm:justify-between">
            <button onClick={()=>setShowSecrets(v=>!v)} className="flex items-center gap-2 text-sm font-extrabold text-slate-600">{showSecrets?<EyeOff size={17}/>:<Eye size={17}/>} {showSecrets?"Hide entered secrets":"Show entered secrets"}</button>
            <div className="flex flex-col gap-2 sm:flex-row"><button className="rounded-xl border border-slate-200 px-4 py-3 text-sm font-extrabold text-[#070a45]">Test connection</button><button onClick={save} className="rounded-xl bg-[#e31545] px-4 py-3 text-sm font-extrabold text-white">Save integration</button></div>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-3">
          <Info icon={<LockKeyhole/>} title="Secrets stay server-side" text="The browser never receives stored app secrets or access tokens after they are saved."/>
          <Info icon={<KeyRound/>} title="Replace without revealing" text="Admins can rotate a credential by entering a replacement; the existing secret remains masked."/>
          <Info icon={<ShieldCheck/>} title="Admin controlled" text="Only authorized Meloli system administrators should be allowed to change publishing credentials."/>
        </div>

        {saved&&<div className="fixed bottom-5 right-5 flex items-center gap-3 rounded-2xl bg-[#070a45] px-5 py-4 text-sm font-extrabold text-white shadow-2xl"><CheckCircle2 size={19} className="text-emerald-400"/> Configuration changes prepared</div>}
      </section>
    </div>
  </main>
}

function Field({label,placeholder}:{label:string;placeholder:string}){return <label className="block"><span className="mb-2 block text-xs font-black uppercase tracking-[.08em] text-slate-500">{label}</span><input className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm font-semibold outline-none transition focus:border-[#070a45] focus:bg-white" placeholder={placeholder}/></label>}
function SecretField({label,placeholder,show}:{label:string;placeholder:string;show:boolean}){return <label className="block"><span className="mb-2 flex items-center gap-2 text-xs font-black uppercase tracking-[.08em] text-slate-500">{label}<LockKeyhole size={13}/></span><input type={show?"text":"password"} autoComplete="new-password" className="h-12 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm font-semibold outline-none transition focus:border-[#070a45] focus:bg-white" placeholder={placeholder}/></label>}
function Info({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="rounded-[1.35rem] border border-slate-200 bg-white p-5"><div className="mb-4 grid h-10 w-10 place-items-center rounded-xl bg-[#070a45]/5 text-[#070a45] [&>svg]:h-5 [&>svg]:w-5">{icon}</div><h4 className="font-black text-[#070a45]">{title}</h4><p className="mt-2 text-sm leading-6 text-slate-500">{text}</p></div>}
