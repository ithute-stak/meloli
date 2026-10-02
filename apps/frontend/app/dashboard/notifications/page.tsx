"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Bell, CheckCheck, CheckCircle2, Loader2 } from "lucide-react";
import { api, getSessionUser } from "@/lib/api";
import { useRealtimeTopics } from "@/app/components/RealtimeBridge";

type Notification={id:number;kind:string;title:string;message:string;read_at?:string|null;created_at:string};

export default function StaffNotificationsPage(){
  const router=useRouter();
  const [items,setItems]=useState<Notification[]>([]);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");

  async function load(silent=false){
    if(!silent)setLoading(true);
    try{setItems(await api<Notification[]>("/api/v1/notifications",{},true));setError("")}
    catch(e){setError(e instanceof Error?e.message:"Unable to load notifications")}
    finally{if(!silent)setLoading(false)}
  }

  useEffect(()=>{
    const user=getSessionUser();
    if(!user||(user.role==="advertiser"&&!user.is_tenant_admin)){router.replace("/login");return}
    load();
  },[router]);
  useRealtimeTopics(["notification","automation","campaign","payment"],()=>load(true));

  const unread=useMemo(()=>items.filter(item=>!item.read_at).length,[items]);
  async function markRead(item:Notification){
    if(item.read_at)return;
    try{await api("/api/v1/notifications/"+item.id+"/read",{method:"POST"},true);await load(true)}
    catch(e){setError(e instanceof Error?e.message:"Unable to update notification")}
  }
  async function markAll(){
    setBusy(true);
    try{await api("/api/v1/notifications/read-all",{method:"POST"},true);await load(true)}
    catch(e){setError(e instanceof Error?e.message:"Unable to update notifications")}
    finally{setBusy(false)}
  }

  return <main className="fb-page">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white shadow-sm">
      <div className="mx-auto flex h-16 max-w-5xl items-center gap-3 px-3 sm:px-4 lg:px-6">
        <Link href="/dashboard" className="fb-icon-button"><ArrowLeft size={18}/></Link>
        <div className="min-w-0 flex-1"><h1 className="text-[17px] font-bold text-slate-900">Notifications</h1><p className="hidden text-xs text-[#65676b] sm:block">Campaign, payment, publishing and automation alerts.</p></div>
        {unread>0&&<button disabled={busy} onClick={markAll} className="fb-secondary inline-flex h-10 items-center gap-2 px-3 text-sm disabled:opacity-50"><CheckCheck size={16}/> Mark all read</button>}
      </div>
    </header>
    <div className="mx-auto max-w-5xl p-3 sm:p-4 lg:p-6">
      {error&&<div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}
      {loading?<div className="grid min-h-72 place-items-center"><Loader2 className="animate-spin text-[#0866ff]"/></div>:items.length===0?<div className="fb-card p-10 text-center"><Bell className="mx-auto text-slate-300"/><h2 className="mt-4 font-bold text-slate-900">No notifications yet</h2><p className="mt-2 text-sm text-[#65676b]">Operational alerts will appear here in realtime.</p></div>:<section className="fb-card overflow-hidden"><div className="border-b border-slate-200 px-4 py-3 text-sm font-semibold text-[#65676b]">{unread} unread · {items.length} total</div><div className="divide-y divide-slate-100">{items.map(item=><button key={item.id} onClick={()=>markRead(item)} className={"flex w-full gap-3 p-4 text-left transition hover:bg-[#f7f8fa] "+(item.read_at?"bg-white":"bg-[#e7f3ff]/55")}><div className={"mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-full "+(item.read_at?"bg-[#e4e6eb] text-[#65676b]":"bg-[#0866ff] text-white")}>{item.read_at?<CheckCircle2 size={17}/>:<Bell size={17}/>}</div><div className="min-w-0 flex-1"><div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"><p className="font-semibold text-slate-900">{item.title}</p><span className="shrink-0 text-xs text-[#8a8d91]">{new Date(item.created_at).toLocaleString()}</span></div><p className="mt-1 text-sm leading-6 text-[#65676b]">{item.message}</p><p className="mt-2 text-[10px] font-semibold text-[#8a8d91]">{item.kind.replaceAll("_"," ")}{item.read_at?" · read":" · unread"}</p></div></button>)}</div></section>}
    </div>
  </main>;
}
