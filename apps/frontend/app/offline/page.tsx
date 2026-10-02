import Link from "next/link";
import { RefreshCw, WifiOff } from "lucide-react";

export default function OfflinePage(){
  return <main className="grid min-h-screen place-items-center bg-[#f5f6fa] p-5"><section className="w-full max-w-lg rounded-[2rem] border border-slate-200 bg-white p-7 text-center shadow-xl shadow-slate-200/40 sm:p-10"><div className="mx-auto grid h-16 w-16 place-items-center rounded-2xl bg-[#070a45] text-white"><WifiOff size={28}/></div><p className="mt-6 text-xs font-black uppercase tracking-[.18em] text-[#e31545]">Connection unavailable</p><h1 className="mt-2 text-3xl font-black text-[#070a45]">Meloli is offline</h1><p className="mt-3 text-sm leading-7 text-slate-500">The app shell is available, but submitting adverts, payments, approvals, publishing and live account data require an internet connection.</p><div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center"><Link href="/" className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#070a45] px-5 py-3 text-sm font-extrabold text-white"><RefreshCw size={16}/> Try again</Link></div></section></main>;
}
