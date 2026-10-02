"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, BadgePercent, Building2, CalendarRange, Loader2 } from "lucide-react";
import { API_URL, api, getSessionUser, getToken } from "@/lib/api";

type Promo={id:number;code:string;percent_off:number;fixed_off:number;uses:number;max_uses?:number|null;active:boolean};
type Plan={id:number;code:string;name:string;monthly_price:number;included_posts:number;active:boolean};
type Advertiser={id:number;full_name:string;business_name?:string|null;email:string};
type Subscription={id:number;user_id:number;advertiser:string;plan_id:number;plan:string;period_start:string;period_end:string;remaining_posts:number;active:boolean};
type Statement={advertiser:{id:number;name:string;email:string};account:{credit_limit:number;credit_used:number;available_credit:number;billing_cycle_day:number;active:boolean};transactions:{payment_id:number;campaign_id:number;campaign:string;amount:number;currency:string;created_at:string;status:string}[]};

export default function CommercialPage(){
 const router=useRouter();
 const [promos,setPromos]=useState<Promo[]>([]);
 const [plans,setPlans]=useState<Plan[]>([]);
 const [advertisers,setAdvertisers]=useState<Advertiser[]>([]);
 const [subscriptions,setSubscriptions]=useState<Subscription[]>([]);
 const [statement,setStatement]=useState<Statement|null>(null);
 const [loading,setLoading]=useState(true);
 const [error,setError]=useState("");
 const [message,setMessage]=useState("");
 const [promo,setPromo]=useState({code:"",percent_off:"",fixed_off:"",max_uses:""});
 const [plan,setPlan]=useState({code:"",name:"",monthly_price:"",included_posts:""});
 const [advertiserId,setAdvertiserId]=useState("");
 const [creditLimit,setCreditLimit]=useState("");
 const [planId,setPlanId]=useState("");

 async function load(){
   setLoading(true);setError("");
   try{
     const [p,pl,a,s]=await Promise.all([
       api<Promo[]>("/api/v1/admin/promos",{},true),
       api<Plan[]>("/api/v1/admin/subscription-plans",{},true),
       api<Advertiser[]>("/api/v1/admin/advertisers",{},true),
       api<Subscription[]>("/api/v1/admin/subscriptions",{},true)
     ]);
     setPromos(p);setPlans(pl);setAdvertisers(a);setSubscriptions(s);
   }catch(e){setError(e instanceof Error?e.message:"Unable to load commercial settings")}
   finally{setLoading(false)}
 }
 useEffect(()=>{const u=getSessionUser();if(!u||u.role!=="super_admin"){router.replace("/dashboard");return;}load();},[router]);

 async function createPromo(e:FormEvent){e.preventDefault();setError("");
   try{await api("/api/v1/admin/promos",{method:"POST",body:JSON.stringify({code:promo.code,percent_off:Number(promo.percent_off||0),fixed_off:Number(promo.fixed_off||0),max_uses:promo.max_uses?Number(promo.max_uses):null,active:true})},true);setPromo({code:"",percent_off:"",fixed_off:"",max_uses:""});setMessage("Promotion created.");await load();}
   catch(e){setError(e instanceof Error?e.message:"Unable to create promotion")}
 }
 async function createPlan(e:FormEvent){e.preventDefault();setError("");
   try{await api("/api/v1/admin/subscription-plans",{method:"POST",body:JSON.stringify({code:plan.code,name:plan.name,description:"",monthly_price:Number(plan.monthly_price),included_posts:Number(plan.included_posts),active:true})},true);setPlan({code:"",name:"",monthly_price:"",included_posts:""});setMessage("Monthly plan created.");await load();}
   catch(e){setError(e instanceof Error?e.message:"Unable to create plan")}
 }
 async function saveCorporate(){if(!advertiserId)return;setError("");
   try{await api("/api/v1/admin/advertisers/"+advertiserId+"/corporate",{method:"PUT",body:JSON.stringify({credit_limit:Number(creditLimit||0),billing_cycle_day:28,active:true})},true);setMessage("Corporate credit updated.");}
   catch(e){setError(e instanceof Error?e.message:"Unable to save credit")}
 }
 async function assignPlan(){if(!advertiserId||!planId)return;setError("");
   try{await api("/api/v1/admin/subscriptions",{method:"POST",body:JSON.stringify({user_id:Number(advertiserId),plan_id:Number(planId),months:1})},true);setMessage("Monthly plan assigned.");await load();}
   catch(e){setError(e instanceof Error?e.message:"Unable to assign plan")}
 }
 async function renewSubscription(id:number){setError("");try{await api("/api/v1/admin/subscriptions/"+id+"/renew",{method:"POST",body:JSON.stringify({months:1})},true);setMessage("Subscription renewed for one month.");await load();}catch(e){setError(e instanceof Error?e.message:"Unable to renew subscription")}}
 async function loadStatement(){if(!advertiserId)return;setError("");try{setStatement(await api<Statement>("/api/v1/admin/advertisers/"+advertiserId+"/corporate/statement",{},true));}catch(e){setStatement(null);setError(e instanceof Error?e.message:"Unable to load corporate statement")}}
 async function settleAccount(){if(!advertiserId)return;setError("");try{await api("/api/v1/admin/advertisers/"+advertiserId+"/corporate/settle",{method:"POST",body:JSON.stringify({amount:null})},true);setMessage("Corporate balance settled.");await loadStatement();}catch(e){setError(e instanceof Error?e.message:"Unable to settle corporate balance")}}
 async function downloadStatement(){if(!advertiserId)return;setError("");try{const token=getToken();const response=await fetch(API_URL+"/api/v1/admin/advertisers/"+advertiserId+"/corporate/statement.pdf",{headers:token?{Authorization:"Bearer "+token}:{}});if(!response.ok)throw new Error("Unable to generate statement PDF");const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="meloli-corporate-statement-"+advertiserId+".pdf";a.click();URL.revokeObjectURL(url);}catch(e){setError(e instanceof Error?e.message:"Unable to download statement")}}

 return <main className="min-h-screen bg-[#f5f6fa] text-slate-900">
  <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex h-20 max-w-[1500px] items-center gap-4 px-4 sm:px-6"><Link href="/dashboard" className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200"><ArrowLeft size={18}/></Link><div><h1 className="font-black text-[#070a45]">Commercial Growth</h1><p className="text-xs text-slate-500">Promotions, corporate credit and monthly advertising plans.</p></div></div></header>
  <div className="mx-auto max-w-[1500px] p-4 sm:p-6 lg:p-8">
   {error&&<div className="mb-5 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-semibold text-rose-700">{error}</div>}
   {message&&<div className="mb-5 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-700">{message}</div>}
   {loading?<div className="grid min-h-64 place-items-center"><Loader2 className="animate-spin text-[#e31545]"/></div>:<div className="grid gap-6 xl:grid-cols-3">
    <section className="rounded-[1.6rem] border border-slate-200 bg-white p-5"><Header icon={<BadgePercent/>} title="Promo codes" text="Offer controlled discounts without changing public package prices."/><form onSubmit={createPromo} className="mt-5 space-y-3"><input className="field uppercase" placeholder="Code" value={promo.code} onChange={e=>setPromo(v=>({...v,code:e.target.value.toUpperCase()}))} required/><div className="grid grid-cols-2 gap-2"><input className="field" type="number" min="0" max="100" placeholder="% off" value={promo.percent_off} onChange={e=>setPromo(v=>({...v,percent_off:e.target.value}))}/><input className="field" type="number" min="0" placeholder="LSL off" value={promo.fixed_off} onChange={e=>setPromo(v=>({...v,fixed_off:e.target.value}))}/></div><input className="field" type="number" min="1" placeholder="Max uses" value={promo.max_uses} onChange={e=>setPromo(v=>({...v,max_uses:e.target.value}))}/><button className="primary">Create promotion</button></form><div className="mt-5 space-y-2">{promos.map(p=><div key={p.id} className="rounded-xl bg-slate-50 p-3"><b className="text-sm text-[#070a45]">{p.code}</b><p className="mt-1 text-xs text-slate-500">{p.percent_off>0?p.percent_off+"% off":"LSL "+p.fixed_off+" off"} · {p.uses}{p.max_uses?"/"+p.max_uses:""} uses</p></div>)}</div></section>
    <section className="rounded-[1.6rem] border border-slate-200 bg-white p-5"><Header icon={<CalendarRange/>} title="Monthly plans" text="Create recurring plans for advertisers who post frequently."/><form onSubmit={createPlan} className="mt-5 space-y-3"><input className="field uppercase" placeholder="Plan code" value={plan.code} onChange={e=>setPlan(v=>({...v,code:e.target.value.toUpperCase()}))} required/><input className="field" placeholder="Plan name" value={plan.name} onChange={e=>setPlan(v=>({...v,name:e.target.value}))} required/><div className="grid grid-cols-2 gap-2"><input className="field" type="number" min="0" placeholder="Monthly LSL" value={plan.monthly_price} onChange={e=>setPlan(v=>({...v,monthly_price:e.target.value}))} required/><input className="field" type="number" min="1" placeholder="Posts" value={plan.included_posts} onChange={e=>setPlan(v=>({...v,included_posts:e.target.value}))} required/></div><button className="primary">Create monthly plan</button></form><div className="mt-5 space-y-2">{plans.map(p=><div key={p.id} className="rounded-xl bg-slate-50 p-3"><b className="text-sm text-[#070a45]">{p.name}</b><p className="mt-1 text-xs text-slate-500">LSL {p.monthly_price.toFixed(2)} · {p.included_posts} adverts</p></div>)}</div></section>
    <section className="rounded-[1.6rem] border border-slate-200 bg-white p-5"><Header icon={<Building2/>} title="Corporate accounts" text="Give approved clients controlled credit or assign a monthly plan."/><div className="mt-5 space-y-3"><select className="field" value={advertiserId} onChange={e=>setAdvertiserId(e.target.value)}><option value="">Select advertiser</option>{advertisers.map(a=><option key={a.id} value={a.id}>{a.business_name||a.full_name} · {a.email}</option>)}</select><input className="field" type="number" min="0" placeholder="Corporate credit limit" value={creditLimit} onChange={e=>setCreditLimit(e.target.value)}/><button onClick={saveCorporate} className="primary" type="button">Save credit account</button><div className="my-4 border-t border-slate-100"/><select className="field" value={planId} onChange={e=>setPlanId(e.target.value)}><option value="">Select monthly plan</option>{plans.filter(p=>p.active).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><button onClick={assignPlan} className="secondary" type="button">Assign monthly plan</button></div></section>
   </div>}
   {!loading&&<div className="mt-6 grid gap-6 xl:grid-cols-2">
    <section className="rounded-[1.6rem] border border-slate-200 bg-white p-5">
      <Header icon={<CalendarRange/>} title="Active subscriptions" text="Renew monthly plans and see remaining advertising allocation."/>
      <div className="mt-5 space-y-3">{subscriptions.length===0?<p className="text-sm text-slate-500">No subscriptions yet.</p>:subscriptions.slice(0,10).map(s=><div key={s.id} className="flex flex-col gap-3 rounded-xl bg-slate-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-sm font-extrabold text-[#070a45]">{s.advertiser}</p><p className="mt-1 text-xs text-slate-500">{s.plan} · {s.remaining_posts} posts left · ends {new Date(s.period_end).toLocaleDateString()}</p></div><button onClick={()=>renewSubscription(s.id)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-extrabold text-[#070a45]">{s.active?"Renew 1 month":"Reactivate"}</button></div>)}</div>
    </section>
    <section className="rounded-[1.6rem] border border-slate-200 bg-white p-5">
      <Header icon={<Building2/>} title="Corporate statement" text="Review credit usage for the selected advertiser and clear the balance when payment is received."/>
      <div className="mt-5 grid gap-2 sm:grid-cols-2"><button type="button" onClick={loadStatement} className="secondary">Load statement</button><button type="button" onClick={downloadStatement} className="primary">Download PDF</button></div>
      {statement&&<div className="mt-4"><div className="grid grid-cols-3 gap-2"><Mini label="Limit" value={"LSL "+statement.account.credit_limit.toFixed(2)}/><Mini label="Used" value={"LSL "+statement.account.credit_used.toFixed(2)}/><Mini label="Available" value={"LSL "+statement.account.available_credit.toFixed(2)}/></div><div className="mt-4 max-h-56 space-y-2 overflow-auto">{statement.transactions.length===0?<p className="text-xs text-slate-500">No corporate-credit transactions.</p>:statement.transactions.map(t=><div key={t.payment_id} className="flex justify-between gap-4 rounded-xl bg-slate-50 p-3 text-xs"><div><b className="text-slate-700">{t.campaign}</b><p className="mt-1 text-slate-400">{new Date(t.created_at).toLocaleDateString()}</p></div><b className="text-[#070a45]">{t.currency} {t.amount.toFixed(2)}</b></div>)}</div>{statement.account.credit_used>0&&<button type="button" onClick={settleAccount} className="mt-4 primary">Mark full balance settled</button>}</div>}
    </section>
   </div>}
  </div>
  <style jsx>{".field{height:2.8rem;width:100%;border-radius:.75rem;border:1px solid #e2e8f0;padding:0 .75rem;font-size:.8125rem;outline:none}.primary,.secondary{height:2.8rem;width:100%;border-radius:.75rem;font-size:.8125rem;font-weight:800}.primary{background:#e31545;color:white}.secondary{background:#070a45;color:white}"}</style>
 </main>
}
function Header({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div><div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl bg-[#070a45]/5 text-[#070a45]">{icon}</div><h2 className="font-black text-[#070a45]">{title}</h2></div><p className="mt-2 text-sm leading-6 text-slate-500">{text}</p></div>}
function Mini({label,value}:{label:string;value:string}){return <div className="rounded-xl bg-slate-50 p-3"><p className="text-[10px] font-black uppercase tracking-wider text-slate-400">{label}</p><p className="mt-1 text-sm font-black text-[#070a45]">{value}</p></div>}
