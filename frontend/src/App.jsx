import { useEffect, useMemo, useState } from 'react';

const fallbackContent = {
  en: {
    heading: 'Level up your downloader UI with Reactbits-inspired sections',
    subheading:
      'Blend Bento grids, fancy spotlights and playful badges to highlight what makes Music Jacker special.',
    cards: [
      {
        title: 'Bento download presets',
        description: 'Highlight MP3, M4A, Opus or MP4 workflows with gradient badges and emoji accents.',
        badge: 'Preset Grid',
        tone: 'from-cyan-400/50 via-sky-500/30 to-blue-600/40',
        icon: '🎚️',
      },
      {
        title: 'Spotlight instructions',
        description: 'Guide users through copyright safe usage with tasteful glow effects and layered cards.',
        badge: 'Spotlight',
        tone: 'from-fuchsia-500/40 via-purple-500/25 to-indigo-600/30',
        icon: '🔦',
      },
      {
        title: 'Story-driven updates',
        description: 'Use Reactbits blog cards to tease release notes or link to Telegram announcements.',
        badge: 'Release Feed',
        tone: 'from-emerald-400/40 via-green-500/40 to-lime-500/30',
        icon: '📻',
      },
    ],
    stats: [
      { label: 'Daily conversions', value: '12K+' },
      { label: 'Avg. latency', value: '1.4s' },
      { label: 'Global locales', value: '15' },
    ],
  },
  ru: {
    heading: 'Укрась раздел сайта компонентами из Reactbits.dev',
    subheading:
      'Комбинируй Bento-сетки, световые эффекты и бейджи, чтобы выделить преимущества Music Jacker.',
    cards: [
      {
        title: 'Готовые пресеты загрузки',
        description: 'Покажи варианты MP3/M4A/Opus/MP4 с цветными бейджами и иконками.',
        badge: 'Bento',
        tone: 'from-cyan-400/50 via-sky-500/30 to-blue-600/40',
        icon: '🎚️',
      },
      {
        title: 'Подсветка инструкций',
        description: 'Расскажи об авторских правах и правилах через карточки со световым «spotlight».',
        badge: 'Glow',
        tone: 'from-fuchsia-500/40 via-purple-500/25 to-indigo-600/30',
        icon: '🔦',
      },
      {
        title: 'Новостная лента',
        description: 'Собери мини-блог о релизах, как на Reactbits, и веди пользователей в Telegram.',
        badge: 'Updates',
        tone: 'from-emerald-400/40 via-green-500/40 to-lime-500/30',
        icon: '📻',
      },
    ],
    stats: [
      { label: 'Ежедневные загрузки', value: '12K+' },
      { label: 'Среднее ожидание', value: '1.4s' },
      { label: 'Доступных языков', value: '15' },
    ],
  },
  es: {
    heading: 'Destaca tu app con tarjetas estilo Reactbits',
    subheading:
      'Crea bloques editoriales, grids modernos y tarjetas brillantes para tus guías de descarga.',
    cards: [
      {
        title: 'Colección de formatos',
        description: 'Presenta los formatos MP3/M4A/Opus/MP4 con fichas suaves y degradados.',
        badge: 'Colección',
        tone: 'from-cyan-400/50 via-sky-500/30 to-blue-600/40',
        icon: '🎚️',
      },
      {
        title: 'Consejos iluminados',
        description: 'Explica buenas prácticas con tarjetas que reaccionan al cursor y sombras fluidas.',
        badge: 'Consejos',
        tone: 'from-fuchsia-500/40 via-purple-500/25 to-indigo-600/30',
        icon: '🔦',
      },
      {
        title: 'Historias del blog',
        description: 'Conecta tus novedades o campañas a través de layouts inspirados en Reactbits.',
        badge: 'Historias',
        tone: 'from-emerald-400/40 via-green-500/40 to-lime-500/30',
        icon: '📻',
      },
    ],
    stats: [
      { label: 'Conversiones/día', value: '12K+' },
      { label: 'Latencia media', value: '1.4s' },
      { label: 'Idiomas activos', value: '15' },
    ],
  },
};

function mergeContent(data = {}) {
  const merged = { ...fallbackContent };
  Object.entries(data).forEach(([lang, payload]) => {
    const base = fallbackContent[lang] || fallbackContent.en;
    merged[lang] = {
      heading: payload.heading ?? base.heading,
      subheading: payload.subheading ?? base.subheading,
      cards: payload.cards ?? base.cards,
      stats: payload.stats ?? base.stats,
    };
  });
  return merged;
}

function BentoCard({ card }) {
  return (
    <article className="reactbits-card group relative rounded-[1.35rem] border border-white/10 bg-slate-900/60 p-6 shadow-2xl transition duration-300 hover:-translate-y-1 hover:shadow-cyan-500/20">
      <span className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-300">
        {card.badge}
      </span>
      <div className="mt-4 flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-800/70 text-2xl">
          <span aria-hidden="true">{card.icon}</span>
        </div>
        <h3 className="text-xl font-semibold text-white">{card.title}</h3>
      </div>
      <p className="mt-4 text-base text-slate-300">{card.description}</p>
      <div
        className={`pointer-events-none absolute inset-0 -z-10 rounded-[1.35rem] bg-gradient-to-br ${card.tone} opacity-80 blur-2xl transition duration-500 group-hover:opacity-100`}
        aria-hidden="true"
      />
      <div className="reactbits-spotlight" aria-hidden="true" />
    </article>
  );
}

function StatsBar({ stats }) {
  return (
    <div className="mt-10 grid gap-4 sm:grid-cols-3">
      {stats.map((stat) => (
        <div
          key={`${stat.label}-${stat.value}`}
          className="rounded-2xl border border-white/10 bg-slate-900/70 p-5 text-center shadow-xl"
        >
          <p className="text-xs uppercase tracking-[0.3em] text-slate-400">{stat.label}</p>
          <p className="mt-2 text-2xl font-semibold text-white">{stat.value}</p>
        </div>
      ))}
    </div>
  );
}

export default function App({ initialLang = 'en', data = {} }) {
  const contentMap = useMemo(() => mergeContent(data), [data]);
  const safeLang = contentMap[initialLang] ? initialLang : 'en';
  const [activeLang, setActiveLang] = useState(safeLang);
  const [content, setContent] = useState(contentMap[safeLang]);

  useEffect(() => {
    setContent(contentMap[activeLang] || contentMap.en);
  }, [activeLang, contentMap]);

  useEffect(() => {
    function handleLanguage(event) {
      const lang = event?.detail;
      if (!lang) return;
      setActiveLang(contentMap[lang] ? lang : 'en');
    }

    window.addEventListener('reactbits-language-change', handleLanguage);
    return () => window.removeEventListener('reactbits-language-change', handleLanguage);
  }, [contentMap]);

  if (!content) {
    return null;
  }

  return (
    <section className="reactbits-section relative mx-auto flex w-full max-w-6xl flex-col gap-6 rounded-[2rem] border border-white/10 bg-slate-950/70 px-6 py-10 text-white shadow-[0_40px_120px_rgba(8,15,40,0.55)]">
      <div className="reactbits-gradient" aria-hidden="true" />
      <div className="relative z-10">
        <p className="text-xs font-semibold uppercase tracking-[0.4em] text-sky-300">
          Reactbits.dev inspiration
        </p>
        <h2 className="mt-4 text-3xl font-semibold leading-tight sm:text-4xl">{content.heading}</h2>
        <p className="mt-3 max-w-3xl text-base text-slate-300 sm:text-lg">{content.subheading}</p>
        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          {content.cards.map((card) => (
            <BentoCard key={`${card.title}-${card.badge}`} card={card} />
          ))}
        </div>
        <StatsBar stats={content.stats} />
      </div>
    </section>
  );
}
