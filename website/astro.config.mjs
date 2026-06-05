import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://alissonjr.github.io',
  base: '/dev-metrics',
  trailingSlash: 'ignore',
  integrations: [
    starlight({
      title: 'dev-metrics',
      description:
        'Plataforma self-hosted de métricas de engenharia. Coleta GitLab + Jira para PostgreSQL, visualiza em Grafana.',
      customCss: [
        '@fontsource-variable/inter',
        '@fontsource-variable/jetbrains-mono',
        './src/styles/custom.css',
      ],
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/alissonjr/dev-metrics',
        },
      ],
      sidebar: [
        {
          label: 'Começar',
          items: [
            { label: 'Início rápido', link: '/getting-started/' },
            { label: 'Arquitetura', link: '/arquitetura/' },
            { label: 'Configuração', link: '/configuracao/' },
          ],
        },
        {
          label: 'Dashboards',
          items: [
            { label: 'GitLab', link: '/dashboards/gitlab/' },
            { label: 'Jira Kanban', link: '/dashboards/jira-kanban/' },
            { label: 'Jira Sprint', link: '/dashboards/jira-sprint/' },
          ],
        },
        {
          label: 'Projeto',
          items: [
            { label: 'Contribuir', link: '/contribuir/' },
            { label: 'Segurança', link: '/seguranca/' },
          ],
        },
      ],
    }),
  ],
});
