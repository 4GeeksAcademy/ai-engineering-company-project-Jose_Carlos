// Website baseline (BP-4) — derived from audit R4-C3 online_render_checks.mjs.
// Served read-only from uis/ (same root as R4). External allowlist: the two hosts the pages fetch today.

import path from "node:path";
import { PAGE_HELPERS, Recorder, launchChrome, openPage, sleep, startStaticServer, waitFor } from "./lib/harness.mjs";

const ALLOWED_EXTERNAL = ["cdn.tailwindcss.com", "images.unsplash.com"];

const policy = ({ method, url }) =>
  (url.hostname === "127.0.0.1" || ALLOWED_EXTERNAL.includes(url.hostname)) && (method === "GET" || method === "HEAD");

const INDEX_DOM = `(()=>{${PAGE_HELPERS}const img=q('#heroImage');return {
  title:document.title, tailwind:tailwindReady(), header_position:cs(q('header')).position,
  header_nav:vis('header nav'), brand:txt('header nav a[href="#home"]'),
  nav_links:qa('header nav ul a').map(a=>vis(a).visible),
  carousel:vis('[aria-roledescription="carousel"]'), hero_h1:vis('#heroTitle'), hero_tag:txt('#heroTag'),
  slide_label:q('#heroSlide')?.getAttribute('aria-label'), dots:qa('#slideDots button').length,
  active_dot:qa('#slideDots button').findIndex(b=>b.getAttribute('aria-current')==='true'),
  beneficios:{cards:qa('#caracteristicas article').length,...vis('#caracteristicas'),h2:vis('#titulo-caracteristicas').visible},
  sobre_nosotros:{cards:qa('#sobre-nosotros article').length,...vis('#sobre-nosotros'),h2:vis('#titulo-sobre-nosotros').visible},
  registro:{inputs:qa('#registerForm input').length,...vis('#registerForm'),h2:vis('#titulo-registro').visible},
  cta:{href:q('#contacto a')?.getAttribute('href'),...vis('#titulo-cta')},
  contacto_address:vis('#contacto address'), footer:vis('footer'),
  mobileMenu:vis('#mobileMenu'), loginPanel:vis('#loginPanel'),
  hidden_audit:hiddenAudit(),
  hero_image:{host:new URL(img.src).host,loaded:img.complete&&img.naturalWidth>0,...vis(img)},
  overflow:overflowX()}})()`;

const slideState = `(()=>{${PAGE_HELPERS}const i=q('#heroImage');return {label:q('#heroSlide').getAttribute('aria-label'),tag:txt('#heroTag'),
  active_dot:qa('#slideDots button').findIndex(b=>b.getAttribute('aria-current')==='true'),image_host:new URL(i.src).host,image_loaded:i.complete&&i.naturalWidth>0}})()`;

function networkChecks(rec, prefix, page) {
  const external = page.state.requests.filter((r) => !r.host.startsWith("127.0.0.1"));
  rec.check(`${prefix}-NET`, "only allowlisted external hosts, GET/HEAD only, nothing blocked",
    page.state.blocked.length === 0 && external.every((r) => ALLOWED_EXTERNAL.includes(r.host.split(":")[0]) && (r.method === "GET" || r.method === "HEAD")),
    { blocked: page.state.blocked, external_hosts: [...new Set(external.map((r) => r.host))] });
}

export async function run({ repoRoot }) {
  const rec = new Recorder("website");
  const server = await startStaticServer(path.join(repoRoot, "uis"));
  const browser = await launchChrome({ allowedHosts: ALLOWED_EXTERNAL });
  const base = `${server.origin}/website/trackflow-web`;
  let cleanup = {};
  try {
    // ---------------------------------------------------------- index.html, desktop 1280x900
    {
      const page = await openPage(browser, { policy });
      const nav = await page.goto(`${base}/index.html`);
      await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}const i=q('#heroImage');return tailwindReady()&&i.complete&&i.naturalWidth>0})()`), 20000);
      const d = await page.eval(INDEX_DOM);
      rec.check("WEB-01", "index.html loads (load event, no navigation error)", nav.loaded && !nav.navigationError, nav);
      rec.check("WEB-02", "index.html: 0 uncaught exceptions at load", page.state.exceptions.length === 0, page.state.exceptions);
      rec.check("WEB-03", "Tailwind runtime present and styles applied (header position fixed)", d.tailwind && d.header_position === "fixed", { tailwind: d.tailwind, header_position: d.header_position });
      rec.check("WEB-04", "title mentions TrackFlow; brand link text is TrackFlow", /TrackFlow/.test(d.title) && d.brand === "TrackFlow", { title: d.title, brand: d.brand });
      rec.check("WEB-05", "header nav visible with >=3 visible desktop links", d.header_nav.visible && d.nav_links.length >= 3 && d.nav_links.every(Boolean), { nav_links: d.nav_links });
      rec.check("WEB-06", "hero carousel visible: h1 visible, 'Slide 1 de 3', 3 dots, first dot active",
        d.carousel.visible && d.hero_h1.visible && d.slide_label === "Slide 1 de 3" && d.dots === 3 && d.active_dot === 0, { slide_label: d.slide_label, dots: d.dots, active_dot: d.active_dot });
      rec.check("WEB-07", "hero image (images.unsplash.com) loaded and visible", d.hero_image.host === "images.unsplash.com" && d.hero_image.loaded && d.hero_image.visible, d.hero_image);
      rec.check("WEB-08", "section Beneficios visible with 4 cards", d.beneficios.visible && d.beneficios.h2 && d.beneficios.cards === 4, d.beneficios);
      rec.check("WEB-09", "section Sobre nosotros visible with 3 cards", d.sobre_nosotros.visible && d.sobre_nosotros.h2 && d.sobre_nosotros.cards === 3, d.sobre_nosotros);
      rec.check("WEB-10", "section Registro visible: form with 2 inputs", d.registro.visible && d.registro.h2 && d.registro.inputs === 2, d.registro);
      rec.check("WEB-11", "CTA visible and links to application.html; contact address and footer visible",
        d.cta.visible && d.cta.href === "application.html" && d.contacto_address.visible && d.footer.visible, { cta: d.cta, address: d.contacto_address.visible, footer: d.footer.visible });
      rec.check("WEB-12", "#mobileMenu and #loginPanel present but hidden on desktop",
        d.mobileMenu.present && !d.mobileMenu.visible && d.loginPanel.present && !d.loginPanel.visible, { mobileMenu: d.mobileMenu, loginPanel: d.loginPanel });
      rec.check("WEB-13", "every .hidden element is display:none unless it has a responsive override",
        d.hidden_audit.shown_without_responsive_override.length === 0, d.hidden_audit);
      rec.check("WEB-14", "no horizontal overflow at 1280px", d.overflow === 0, { overflow_px: d.overflow });

      // Carousel: next -> slide 2 -> slide 3 -> wraps to slide 1 (no autoplay in the page).
      const initialTag = d.hero_tag;
      const seen = [];
      for (const expected of [2, 3, 1]) {
        await page.eval(`document.querySelector('#nextSlide').click();true`);
        const s = await waitFor(async () => {
          const st = await page.eval(slideState);
          return st.label === `Slide ${expected} de 3` && st.image_loaded ? st : null;
        }, 15000);
        seen.push(s || (await page.eval(slideState)));
      }
      const [s2, s3, s1] = seen;
      rec.check("WEB-15", "carousel next: slide 2 active (label, dot 1, new tag, new image loaded)",
        s2?.label === "Slide 2 de 3" && s2.active_dot === 1 && s2.tag !== initialTag && s2.image_loaded && s2.image_host === "images.unsplash.com", s2);
      rec.check("WEB-16", "carousel next again: slide 3 active with distinct tag and image loaded",
        s3?.label === "Slide 3 de 3" && s3.active_dot === 2 && s3.tag !== s2?.tag && s3.tag !== initialTag && s3.image_loaded, s3);
      rec.check("WEB-17", "carousel next from slide 3 wraps to slide 1 with the initial tag",
        s1?.label === "Slide 1 de 3" && s1.active_dot === 0 && s1.tag === initialTag, s1);

      // Registration form: empty submit reveals at least one validation message (no alert, no request).
      const reqsBefore = page.state.requests.length;
      const reg = await page.eval(`(()=>{${PAGE_HELPERS}const f=q('#registerForm');
        const hiddenBefore=qa('#registerForm .hidden').filter(e=>cs(e).display==='none').length;
        f.requestSubmit();
        return new Promise(r=>setTimeout(()=>r({hiddenBefore,
          hiddenAfter:qa('#registerForm .hidden').filter(e=>cs(e).display==='none').length,
          visibleErrors:qa('#registerForm p,#registerForm span').filter(e=>/obligatorio|v[aá]lido/i.test(e.textContent)&&vis(e).visible).length}),300))})()`);
      rec.check("WEB-18", "empty register submit shows a visible validation error and sends no request",
        reg.visibleErrors >= 1 && reg.hiddenAfter < reg.hiddenBefore && page.state.requests.length === reqsBefore, reg);

      const appStatus = await page.eval(`fetch('application.html',{method:'HEAD'}).then(r=>r.status)`);
      rec.check("WEB-19", "relative link application.html resolves (HTTP 200) under uis/ root", appStatus === 200, { status: appStatus });
      networkChecks(rec, "WEB-20", page);
      await page.close();
    }

    // ---------------------------------------------------------- index.html, mobile 390x844
    {
      const page = await openPage(browser, { policy, viewport: { width: 390, height: 844, mobile: true } });
      const nav = await page.goto(`${base}/index.html`);
      await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}return tailwindReady()})()`), 20000);
      await sleep(500);
      const m = await page.eval(`(()=>{${PAGE_HELPERS}return {menuButton:vis('#menuButton'),mobileMenu:vis('#mobileMenu'),desktopNav:vis('header nav ul'),
        hero_h1:vis('#heroTitle'),overflow:overflowX(),hidden_audit:hiddenAudit(),expanded:q('#menuButton').getAttribute('aria-expanded')}})()`);
      rec.check("WEB-M01", "mobile: loads with 0 uncaught exceptions", nav.loaded && page.state.exceptions.length === 0, page.state.exceptions);
      rec.check("WEB-M02", "mobile: menu button visible, desktop nav list hidden, hero h1 visible",
        m.menuButton.visible && !m.desktopNav.visible && m.hero_h1.visible, { menuButton: m.menuButton.visible, desktopNav: m.desktopNav.visible, hero_h1: m.hero_h1.visible });
      rec.check("WEB-M03", "mobile: menu initially closed and every .hidden element display:none",
        !m.mobileMenu.visible && m.hidden_audit.computed_display_none === m.hidden_audit.hidden_class_elements, m.hidden_audit);
      rec.check("WEB-M04", "mobile: no horizontal overflow at 390px", m.overflow === 0, { overflow_px: m.overflow });
      await page.eval(`document.querySelector('#menuButton').click();true`);
      const opened = await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}const v=vis('#mobileMenu');return v.visible?{visible:true,expanded:q('#menuButton').getAttribute('aria-expanded')}:null})()`), 3000);
      rec.check("WEB-M05", "mobile: menu button opens #mobileMenu and sets aria-expanded=true", opened?.visible && opened.expanded === "true", opened);
      await page.eval(`document.querySelector('#menuButton').click();true`);
      const closed = await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}return !vis('#mobileMenu').visible?{expanded:q('#menuButton').getAttribute('aria-expanded')}:null})()`), 3000);
      rec.check("WEB-M06", "mobile: second click closes the menu (aria-expanded=false)", closed?.expanded === "false", closed);
      networkChecks(rec, "WEB-M07", page);
      await page.close();
    }

    // ---------------------------------------------------------- application.html
    {
      const page = await openPage(browser, { policy });
      const nav = await page.goto(`${base}/application.html`);
      await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}return tailwindReady()})()`), 20000);
      await sleep(300);
      const a = await page.eval(`(()=>{${PAGE_HELPERS}return {title:document.title,header:vis('header').visible,h1:vis('#titulo-aplicacion').visible,
        forms:qa('form').map(f=>({id:f.id,visible:vis(f).visible})),tabs:[txt('#tabParticulares'),txt('#tabEmpresas')],
        particulares:vis('#panelParticulares').visible,empresas:vis('#panelEmpresas').visible,hidden_audit:hiddenAudit(),overflow:overflowX()}})()`);
      rec.check("APP-01", "application.html loads with 0 uncaught exceptions", nav.loaded && page.state.exceptions.length === 0, page.state.exceptions);
      rec.check("APP-02", "title mentions TrackFlow; header and h1 visible", /TrackFlow/.test(a.title) && a.header && a.h1, { title: a.title, header: a.header, h1: a.h1 });
      rec.check("APP-03", "two tabs (Particulares, Empresas); Particulares panel shown, Empresas hidden",
        a.tabs[0] === "Particulares" && a.tabs[1] === "Empresas" && a.particulares && !a.empresas, { tabs: a.tabs, particulares: a.particulares, empresas: a.empresas });
      rec.check("APP-04", "forms: sendForm visible, businessForm hidden",
        a.forms.some((f) => f.id === "sendForm" && f.visible) && a.forms.some((f) => f.id === "businessForm" && !f.visible), a.forms);
      rec.check("APP-05", "every .hidden element is display:none (no responsive override needed)",
        a.hidden_audit.shown_without_responsive_override.length === 0, a.hidden_audit);
      rec.check("APP-06", "no horizontal overflow at 1280px", a.overflow === 0, { overflow_px: a.overflow });
      await page.eval(`document.querySelector('#tabEmpresas').click();true`);
      const sw = await waitFor(() => page.eval(`(()=>{${PAGE_HELPERS}const e=vis('#panelEmpresas').visible,p=vis('#panelParticulares').visible;return e&&!p?{empresas:e,particulares:p}:null})()`), 3000);
      rec.check("APP-07", "clicking Empresas shows its panel and hides Particulares", !!sw, sw);
      networkChecks(rec, "APP-08", page);
      await page.close();
    }
  } catch (e) {
    rec.abort(e);
  } finally {
    cleanup = await browser.close();
    await server.close();
  }
  rec.check("WEB-CLEAN", "temporary Chrome profile removed", cleanup.profileRemoved, cleanup);
  return rec;
}
