export enum DashboardCommand {
  initializing = 'initializing',
  loading = 'loading',
  pages = 'pages',
  searchPages = 'searchPages',
  settings = 'settings',
  media = 'media',
  viewData = 'viewData',
  mediaUpdate = 'mediaUpdate',
  dataFileEntries = 'dataFileEntries',
  searchReady = 'searchReady',

  // Taxonomy dashboard
  setTaxonomyData = 'setTaxonomyData',

  // Image processing
  imageProcessingProviders = 'imageProcessingProviders',
  imageProcessingPrompts = 'imageProcessingPrompts',
  imageProcessingCost = 'imageProcessingCost',
  showNotification = 'showNotification'
}
