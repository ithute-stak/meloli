import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meloli Airwaves | Advertise with confidence",
  description: "Submit, pay, approve and manage advertising campaigns with Meloli Airwaves Media.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
