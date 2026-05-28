// Main Gallery Components
export { ResultGallery } from './ResultGallery'
export { Lightbox } from './Lightbox'

// Specialized Viewers
export { BrainMapViewer } from './viewers/BrainMapViewer'
export { TableViewer } from './viewers/TableViewer'
export { GraphViewer } from './viewers/GraphViewer'
export { ReportViewer } from './viewers/ReportViewer'

// Hooks
export { useGallerySelection } from '../../hooks/use-gallery-selection'
export { useLightbox } from '../../hooks/use-lightbox'

// Utilities
export {
  formatFileSize,
  formatDuration,
  filterItems,
  sortItems,
  paginateItems,
  downloadItemsAsZip,
  exportItemsAsCSV,
  generateShareLink,
  copyItemsToClipboard,
  getUniqueValues,
  getAnalysisStats
} from '../../lib/gallery-utils'

export {
  ThumbnailGenerator,
  generateThumbnailFromUrl,
  generateThumbnailFromData
} from '../../lib/thumbnail-generator'

// Types
export type { GalleryItem, FilterState } from '../../lib/gallery-utils'