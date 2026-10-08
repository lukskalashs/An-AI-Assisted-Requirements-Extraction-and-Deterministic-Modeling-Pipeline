export function convertSvgToPng(svg: Blob): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const sourceUrl = window.URL.createObjectURL(svg);
    const image = new Image();
    image.onload = () => {
      const scale = 2;
      const canvas = document.createElement('canvas');
      canvas.width = image.naturalWidth * scale;
      canvas.height = image.naturalHeight * scale;
      const context = canvas.getContext('2d');
      if (!context) {
        window.URL.revokeObjectURL(sourceUrl);
        reject(new Error('Canvas is unavailable for PNG export.'));
        return;
      }
      context.fillStyle = '#ffffff';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.scale(scale, scale);
      context.drawImage(image, 0, 0);
      canvas.toBlob(blob => {
        window.URL.revokeObjectURL(sourceUrl);
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error('The browser could not encode the diagram as PNG.'));
        }
      }, 'image/png');
    };
    image.onerror = () => {
      window.URL.revokeObjectURL(sourceUrl);
      reject(new Error('The generated SVG could not be loaded for PNG export.'));
    };
    image.src = sourceUrl;
  });
}
