// Remind Me Bro brand: the logo picks the version that reads on the current background.
import logoOnLight from "../assets/brand/logo-light-bg.png";
import logoOnDark from "../assets/brand/logo-dark-bg.png";
import icon from "../assets/brand/icon-192.png";
import iconSmall from "../assets/brand/icon-64.png";

export const BRAND = { icon, iconSmall, logoOnLight, logoOnDark };

/** Full logo. tone="auto" follows the light/dark theme; "dark" is for dark backgrounds (e.g. the sign-in hero). */
export function BrandLogo({ tone = "auto", className = "" }: { tone?: "auto" | "dark"; className?: string }) {
  if (tone === "dark") return <img className={`brand-logo ${className}`} src={logoOnDark} alt="Remind Me Bro" />;
  return (
    <span className={`brand-logo ${className}`}>
      <img className="on-light" src={logoOnLight} alt="Remind Me Bro" />
      <img className="on-dark" src={logoOnDark} alt="" aria-hidden />
    </span>
  );
}

/** Uses the icon as the browser tab icon and the home-screen icon. */
export function setFavicon(): void {
  const set = (rel: string, href: string) => {
    let link = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
    if (!link) { link = document.createElement("link"); link.rel = rel; document.head.appendChild(link); }
    link.href = href;
    link.type = "image/png";
  };
  set("icon", iconSmall);
  set("apple-touch-icon", icon);
}
