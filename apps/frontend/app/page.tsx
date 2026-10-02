import Link from "next/link";
import { ArrowRight, BadgeCheck, BarChart3, CalendarClock, CheckCircle2, Megaphone, ShieldCheck, Sparkles } from "lucide-react";

const steps = [
  ["01", "Create your advert", "Add your message, artwork, video and preferred publishing date."],
  ["02", "Pay securely", "Choose a Meloli advertising package and submit your payment reference."],
  ["03", "Meloli reviews", "The editorial team approves, requests changes or schedules the campaign."],
  ["04", "Track the result", "Follow status, publication details and campaign performance from one dashboard."],
];

export default function Home() {
  return (
    <main className="min-h-screen bg-white text-slate-950">
      <header className="fixed inset-x-0 top-0 z-50 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <Link href="/" className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-[#070a45] text-white shadow-lg"><Megaphone size={20} /></div>
            <div><div className="text-lg font-black tracking-tight"><span className="text-[#070a45]">MELOLI</span><span className="text-[#e31545]">AIRWAVES</span></div><div className="text-[10px] font-bold uppercase tracking-[.2em] text-slate-500">Media Advertising Portal</div></div>
          </Link>
          <nav className="hidden items-center gap-8 text-sm font-semibold text-slate-600 md:flex"><a href="#how">How it works</a><a href="#benefits">Benefits</a><a href="#publishers">For Meloli</a></nav>
          <div className="flex items-center gap-2"><Link href="/login" className="hidden rounded-xl px-4 py-2.5 text-sm font-bold text-[#070a45] sm:block">Sign in</Link><Link href="/login" className="rounded-xl bg-[#070a45] px-4 py-2.5 text-sm font-bold text-white shadow-lg shadow-indigo-950/20">Advertise now</Link></div>
        </div>
      </header>

      <section className="meloli-grid relative overflow-hidden pt-32">
        <div className="absolute -left-20 top-20 h-72 w-72 rounded-full bg-[#e31545]/10 blur-3xl"/><div className="absolute -right-16 top-12 h-96 w-96 rounded-full bg-[#070a45]/10 blur-3xl"/>
        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 pb-24 pt-10 sm:px-6 lg:grid-cols-[1.08fr_.92fr] lg:px-8 lg:pb-32">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#e31545]/20 bg-[#e31545]/5 px-3 py-1.5 text-xs font-extrabold uppercase tracking-[.14em] text-[#c8123a]"><Sparkles size={14}/> Advertising made simple</div>
            <h1 className="max-w-3xl text-5xl font-black leading-[.96] tracking-[-.05em] text-[#070a45] sm:text-6xl lg:text-7xl">Your message.<br/><span className="text-[#e31545]">Meloli&apos;s audience.</span><br/>One simple platform.</h1>
            <p className="mt-7 max-w-xl text-lg leading-8 text-slate-600">Create and manage paid adverts, collaborate with the Meloli Airwaves team, receive approvals and follow your campaign from submission to publication.</p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row"><Link href="/login" className="inline-flex items-center justify-center gap-2 rounded-2xl bg-[#e31545] px-6 py-4 font-extrabold text-white shadow-xl shadow-rose-600/20">Start an advert <ArrowRight size={18}/></Link><Link href="/register-page" className="inline-flex items-center justify-center rounded-2xl border border-[#070a45] bg-white px-6 py-4 font-extrabold text-[#070a45]">Create a portal for your Page</Link><a href="#how" className="inline-flex items-center justify-center rounded-2xl border border-slate-200 bg-white px-6 py-4 font-extrabold text-[#070a45]">See how it works</a></div>
            <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm font-semibold text-slate-600"><span className="flex items-center gap-2"><CheckCircle2 size={16} className="text-emerald-600"/>Transparent workflow</span><span className="flex items-center gap-2"><CheckCircle2 size={16} className="text-emerald-600"/>Mobile friendly</span><span className="flex items-center gap-2"><CheckCircle2 size={16} className="text-emerald-600"/>Meloli approved</span></div>
          </div>

          <div className="relative">
            <div className="shadow-soft rounded-[2rem] border border-slate-200 bg-white p-3 sm:p-5">
              <div className="rounded-[1.5rem] bg-[#070a45] p-5 text-white sm:p-7">
                <div className="flex items-center justify-between"><div><p className="text-xs font-bold uppercase tracking-[.18em] text-white/60">Campaign workspace</p><h2 className="mt-1 text-2xl font-black">Good morning, Mpho</h2></div><div className="grid h-12 w-12 place-items-center rounded-2xl bg-white/10"><BarChart3/></div></div>
                <div className="mt-7 grid grid-cols-2 gap-3"><div className="rounded-2xl bg-white/10 p-4"><p className="text-xs text-white/60">Active adverts</p><p className="mt-2 text-3xl font-black">04</p></div><div className="rounded-2xl bg-white/10 p-4"><p className="text-xs text-white/60">Awaiting review</p><p className="mt-2 text-3xl font-black">02</p></div></div>
              </div>
              <div className="grid gap-3 p-3 sm:p-4"><div className="flex items-center gap-4 rounded-2xl border border-slate-100 p-4"><div className="grid h-11 w-11 place-items-center rounded-xl bg-amber-50 text-amber-600"><CalendarClock size={20}/></div><div className="min-w-0 flex-1"><p className="font-extrabold text-slate-900">October promotion</p><p className="truncate text-sm text-slate-500">Scheduled · 03 Oct, 10:00</p></div><span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">Approved</span></div><div className="flex items-center gap-4 rounded-2xl border border-slate-100 p-4"><div className="grid h-11 w-11 place-items-center rounded-xl bg-rose-50 text-[#e31545]"><Megaphone size={20}/></div><div className="min-w-0 flex-1"><p className="font-extrabold text-slate-900">Weekend offer</p><p className="truncate text-sm text-slate-500">Submitted today</p></div><span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-700">In review</span></div></div>
            </div>
          </div>
        </div>
      </section>

      <section id="how" className="bg-[#f7f8fc] py-24"><div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8"><div className="max-w-2xl"><p className="text-xs font-black uppercase tracking-[.2em] text-[#e31545]">How it works</p><h2 className="mt-3 text-4xl font-black tracking-tight text-[#070a45]">From idea to published advert.</h2></div><div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-4">{steps.map(([n,t,d])=><div key={n} className="rounded-3xl border border-slate-200 bg-white p-6"><span className="text-sm font-black text-[#e31545]">{n}</span><h3 className="mt-8 text-xl font-black text-[#070a45]">{t}</h3><p className="mt-3 text-sm leading-6 text-slate-600">{d}</p></div>)}</div></div></section>

      <section id="benefits" className="py-24"><div className="mx-auto grid max-w-7xl gap-10 px-4 sm:px-6 lg:grid-cols-3 lg:px-8"><div className="lg:col-span-1"><p className="text-xs font-black uppercase tracking-[.2em] text-[#e31545]">Built for trust</p><h2 className="mt-3 text-4xl font-black tracking-tight text-[#070a45]">One source of truth for every advert.</h2></div><div className="grid gap-5 sm:grid-cols-2 lg:col-span-2"><Feature icon={<ShieldCheck/>} title="Controlled approval" text="Nothing reaches publication before a Meloli reviewer approves it."/><Feature icon={<BadgeCheck/>} title="Clear accountability" text="Keep submissions, comments, approvals, payment status and publishing history together."/><Feature icon={<CalendarClock/>} title="Smarter scheduling" text="Reserve preferred dates and let Meloli manage the final publishing calendar."/><Feature icon={<BarChart3/>} title="Useful reporting" text="Give clients a clear view of campaign status and available performance metrics."/></div></div></section>

      <section id="publishers" className="mx-auto max-w-7xl px-4 pb-24 sm:px-6 lg:px-8"><div className="overflow-hidden rounded-[2rem] bg-[#070a45] px-6 py-12 text-white sm:px-10 lg:flex lg:items-center lg:justify-between lg:px-14"><div><p className="text-sm font-bold text-white/60">MELOLI AIRWAVES MEDIA</p><h2 className="mt-2 max-w-2xl text-3xl font-black sm:text-4xl">Professional advertising management without sharing Facebook credentials.</h2></div><Link href="/login" className="mt-7 inline-flex shrink-0 items-center gap-2 rounded-2xl bg-white px-6 py-4 font-extrabold text-[#070a45] lg:mt-0">Open portal <ArrowRight size={18}/></Link></div></section>

      <footer className="border-t border-slate-200 bg-white"><div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-8 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8"><p>© 2026 Meloli Airwaves Media. Advertising Portal.</p><p>The Online Media Everyone is Following.</p></div></footer>
    </main>
  );
}

function Feature({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="rounded-3xl border border-slate-200 bg-white p-6"><div className="grid h-11 w-11 place-items-center rounded-xl bg-[#070a45]/5 text-[#070a45]">{icon}</div><h3 className="mt-5 text-lg font-black text-[#070a45]">{title}</h3><p className="mt-2 text-sm leading-6 text-slate-600">{text}</p></div>}
