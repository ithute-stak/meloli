import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Meloli Airwaves Advertising Portal",
    short_name: "Meloli Ads",
    description: "Create, approve, publish and track advertising campaigns with Meloli Airwaves Media.",
    start_url: "/",
    display: "standalone",
    background_color: "#f5f6fa",
    theme_color: "#070a45",
    orientation: "portrait-primary",
    categories: ["business", "marketing", "productivity"],
    icons: [
      { src: "/icons/meloli-pwa.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icons/meloli-pwa-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" }
    ],
  };
}
