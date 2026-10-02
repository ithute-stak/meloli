import { NextRequest, NextResponse } from "next/server";

export async function proxy(request: NextRequest) {
  if (request.nextUrl.pathname !== "/") return NextResponse.next();

  const host = (request.headers.get("host") || "").split(":")[0].toLowerCase();
  if (!host || host === "localhost" || host === "127.0.0.1") return NextResponse.next();

  const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  try {
    const response = await fetch(api + "/api/v1/tenants/resolve?host=" + encodeURIComponent(host), {
      headers: { "Accept": "application/json" },
      cache: "no-store",
    });
    if (!response.ok) return NextResponse.next();
    const tenant = await response.json();
    if (!tenant?.slug) return NextResponse.next();
    const url = request.nextUrl.clone();
    url.pathname = "/p/" + tenant.slug;
    return NextResponse.rewrite(url);
  } catch {
    return NextResponse.next();
  }
}

export const config = { matcher: ["/"] };
