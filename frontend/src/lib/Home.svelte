<script lang="ts">
  import { datasets } from './data/datasets.svelte'
  import { session } from './stores/session.svelte'
  import { BASE_PATH } from './api'

  let { onNavigate }: { onNavigate: (view: 'trace' | 'calibrate' | 'force-ext') => void } = $props()

  // Rough at-a-glance counters for the "session" strip. Traces are the
  // openable entries across every uploaded dataset.
  let datasetCount = $derived(datasets.datasets.length)
  let traceCount = $derived(
    datasets.datasets.reduce((n, ds) => n + ds.entries.filter((e) => e.kind === 'trace').length, 0),
  )
</script>

<main class="home">
  <section class="hero">
    <img src="{BASE_PATH}/logo-hero.png" alt="SalaFleezers logo" class="hero-logo" />
    <div class="hero-copy stack">
      <p class="label">Optical-tweezers force spectroscopy</p>
      <h1 class="hero-title">SalaFleezer</h1>
      <p class="hero-lede">
        Turn raw SalaFleezer QPD acquisitions into calibrated, analysis-ready force spectroscopy
        data &mdash; load and validate traces, calibrate trap stiffness with Lorentzian
        power-spectrum fitting, and convert detector signals into force
        <span class="mono">(pN)</span> and extension <span class="mono">(nm)</span>.
      </p>

      <div class="cta row-center">
        <button class="primary" onclick={() => onNavigate('trace')}>Open Trace Viewer</button>
        <button onclick={() => onNavigate('calibrate')}>Calibrate</button>
        <button onclick={() => onNavigate('force-ext')}>Force-Extension</button>
      </div>

      <div class="session-strip">
        {#if session.sessionId}
          <span class="label">Session</span>
          <span class="mono" title={session.sessionId}>{session.sessionId.slice(0, 8)}</span>
          <span class="sep">·</span>
          <span class="mono">{datasetCount}</span>
          <span class="dim">dataset{datasetCount === 1 ? '' : 's'}</span>
          <span class="sep">·</span>
          <span class="mono">{traceCount}</span>
          <span class="dim">trace{traceCount === 1 ? '' : 's'}</span>
        {:else}
          <span class="dim">Drop a folder of <span class="mono">.dat</span> files into the rail to begin.</span>
        {/if}
      </div>
    </div>
  </section>

  <section class="features">
    <article class="card feature stack">
      <p class="label">01 &mdash; Inspect</p>
      <h3>Trace Viewer</h3>
      <p class="feature-body">
        Browse raw QPD voltage traces with sidecar position and fluorescence channels. Select,
        zoom, crop, and measure any range directly on the plot.
      </p>
      <button class="ghost feature-link" onclick={() => onNavigate('trace')}>Open &rarr;</button>
    </article>

    <article class="card feature stack">
      <p class="label">02 &mdash; Calibrate</p>
      <h3>Trap stiffness</h3>
      <p class="feature-body">
        Fit Lorentzian power spectra to recover trap stiffness and detector sensitivity, then
        convert detector volts into calibrated force and extension.
      </p>
      <button class="ghost feature-link" onclick={() => onNavigate('calibrate')}>Open &rarr;</button>
    </article>

    <article class="card feature stack">
      <p class="label">03 &mdash; Analyze</p>
      <h3>Force-Extension</h3>
      <p class="feature-body">
        Fit force-extension curves and run every analysis routine &mdash; KDE, kinetics, MSD,
        velocity, PWD, and violin summaries &mdash; over your calibrated traces.
      </p>
      <button class="ghost feature-link" onclick={() => onNavigate('force-ext')}>Open &rarr;</button>
    </article>
  </section>

  <footer class="home-footer">
    <span class="dim">Headless? Run <span class="mono">sfz gui</span> or the <span class="mono">sfz</span> CLI.</span>
    <span class="dim">Press <span class="mono">1</span> / <span class="mono">2</span> / <span class="mono">3</span> to switch views, <span class="mono">t</span> to toggle theme.</span>
  </footer>
</main>

<style>
  .home {
    flex: 1;
    min-width: 0;
    max-width: 960px;
    margin: 0 auto;
    padding: var(--s-6) var(--s-4) var(--s-5);
    width: 100%;
  }

  .hero {
    display: flex;
    align-items: center;
    gap: var(--s-6);
    padding-bottom: var(--s-6);
    border-bottom: 1px solid var(--border);
  }
  .hero-logo {
    width: 220px;
    height: 220px;
    flex: 0 0 auto;
    object-fit: contain;
    /* The source PNG has a solid white background, so frame it as a
       deliberate logo plate rather than letting it read as a stray white
       box against the dark theme. */
    background: #ffffff;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--s-3);
  }
  .hero-copy {
    min-width: 0;
  }
  .hero-title {
    font-size: 40px;
    letter-spacing: -0.02em;
    line-height: 1.05;
  }
  .hero-lede {
    margin: 0;
    color: var(--text);
    max-width: 52ch;
    line-height: 1.55;
  }
  .cta {
    margin-top: var(--s-2);
  }

  .session-strip {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--s-2);
    margin-top: var(--s-3);
    padding-top: var(--s-3);
    border-top: 1px solid var(--border);
    font-size: var(--text-xs);
  }
  .session-strip .sep {
    color: var(--border-strong);
  }

  .features {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--s-3);
    margin-top: var(--s-6);
  }
  .feature {
    display: flex;
    flex-direction: column;
  }
  .feature h3 {
    font-size: var(--text-lg);
  }
  .feature-body {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text);
    line-height: 1.5;
    flex: 1;
  }
  .feature-link {
    align-self: flex-start;
    margin-top: var(--s-1);
    font-size: var(--text-xs);
    padding-left: 0;
    padding-right: 0;
  }

  .home-footer {
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--s-2);
    margin-top: var(--s-6);
    padding-top: var(--s-3);
    border-top: 1px solid var(--border);
    font-size: var(--text-xs);
  }

  @media (max-width: 760px) {
    .hero {
      flex-direction: column;
      text-align: center;
      gap: var(--s-4);
    }
    .hero-logo {
      width: 160px;
      height: 160px;
    }
    .hero-copy :global(.cta),
    .session-strip {
      justify-content: center;
    }
    .features {
      grid-template-columns: 1fr;
    }
  }
</style>
