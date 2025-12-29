/**
 * Centralized configuration for Mermaid diagrams.
 * Defines the default design (colors, shapes, etc.) for the documentation.
 * Uses the app's design tokens for consistency.
 */
if (window.mermaid) {
  // Get CSS custom properties from the document
  const style = getComputedStyle(document.documentElement);
  
  // Extract design tokens
  const primary = style.getPropertyValue('--color-primary').trim() || '#007bff';
  const primarySubtle = style.getPropertyValue('--color-primary-subtle').trim() || '#f0f7ff';
  const fg = style.getPropertyValue('--color-fg').trim() || '#111111';
  const fgMuted = style.getPropertyValue('--color-fg-muted').trim() || '#6c757d';
  const success = style.getPropertyValue('--color-success').trim() || '#28a745';
  const successSubtle = style.getPropertyValue('--color-success-subtle').trim() || '#d4edda';
  const warning = style.getPropertyValue('--color-warning').trim() || '#ffc107';
  const warningSubtle = style.getPropertyValue('--color-warning-subtle').trim() || '#fff3cd';
  const info = style.getPropertyValue('--color-info').trim() || '#17a2b8';
  const radiusMd = style.getPropertyValue('--radius-md').trim() || '8px';
  
  mermaid.initialize({
    startOnLoad: true,
    theme: 'base',
    themeVariables: {
      // Primary elements use the app's primary color
      primaryColor: primarySubtle,
      primaryTextColor: primary,
      primaryBorderColor: primary,
      
      // Lines and connectors
      lineColor: fgMuted,
      
      // Secondary and tertiary colors for variety
      secondaryColor: warningSubtle,
      secondaryTextColor: fg,
      secondaryBorderColor: warning,
      
      tertiaryColor: successSubtle,
      tertiaryTextColor: fg,
      tertiaryBorderColor: success,
      
      // Background
      background: primarySubtle,
      mainBkg: primarySubtle,
      secondBkg: warningSubtle,
      
      // Text
      textColor: fg,
      fontFamily: style.getPropertyValue('--font-sans').trim() || 'system-ui, -apple-system, sans-serif',
      fontSize: '14px',
      
      // Borders (rounded corners matching app's design)
      nodeBorder: primary,
      clusterBkg: primarySubtle,
      clusterBorder: primary,
      
      // Edge styling
      edgeLabelBackground: primarySubtle,
      
      // Activity/State diagram colors
      labelColor: fg,
      labelTextColor: fg,
      actorBorder: primary,
      actorBkg: primarySubtle,
      actorTextColor: fg,
      actorLineColor: fgMuted,
      signalColor: fg,
      signalTextColor: fg
    },
    flowchart: {
      useMaxWidth: true,
      htmlLabels: true,
      curve: 'basis',
      padding: 15,
      // Note: Mermaid doesn't directly support border-radius via config,
      // but we can adjust via CSS in docs.css
    },
    sequence: {
      diagramMarginX: 15,
      diagramMarginY: 15,
      boxMargin: 10,
      boxTextMargin: 5,
      noteMargin: 10,
      messageMargin: 35,
      mirrorActors: true,
      useMaxWidth: true
    },
    gantt: {
      useMaxWidth: true,
      fontSize: 14
    }
  });
}
