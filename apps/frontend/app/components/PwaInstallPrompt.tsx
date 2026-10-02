"use client";

import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

export default function PwaInstallPrompt(){
  const [promptEvent,setPromptEvent]=useState<InstallPromptEvent|null>(null);
  const [hidden,setHidden]=useState(false);

  useEffect(()=>{
    const handler=(event:Event)=>{
      event.preventDefault();
      setPromptEvent(event as InstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt",handler);
    return ()=>window.removeEventListener("beforeinstallprompt",handler);
  },[]);

  if(!promptEvent||hidden)return null;

  async function install(){
    await promptEvent?.prompt();
    const choice=await promptEvent?.userChoice;
    if(choice?.outcome==="accepted")setPromptEvent(null);
    else setHidden(true);
  }

  return <div className="fixed inset-x-3 bottom-3 z-[100] mx-auto max-w-md rounded-xl border border-slate-200 bg-white p-4 shadow-2xl shadow-slate-900/20 sm:left-auto sm:right-4 sm:mx-0">
    <div className="flex items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[#070a45] text-white"><Download size={18}/></div><div className="min-w-0 flex-1"><p className="font-bold text-slate-900">Install Meloli Ads</p><p className="mt-1 text-xs leading-5 text-slate-500">Add the advertising portal to this device for faster standalone access.</p><button onClick={install} className="mt-3 rounded-xl bg-[#0866ff] px-4 py-2 text-xs font-semibold text-white">Install app</button></div><button onClick={()=>setHidden(true)} aria-label="Dismiss install prompt" className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-400 hover:bg-slate-100"><X size={16}/></button></div>
  </div>;
}
