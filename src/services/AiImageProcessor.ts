import { Logger, Notifications, Settings } from '../helpers';
import * as l10n from '@vscode/l10n';
import { LocalizationKey } from '../localization';
import * as fs from 'fs';
import * as path from 'path';
import fetch from 'node-fetch';

export interface ImageProcessingOptions {
  prompt: string;
  provider?: 'openai' | 'stability' | 'custom';
  model?: string;
  size?: string;
  quality?: 'standard' | 'hd';
  style?: 'vivid' | 'natural';
}

export interface ProcessedImageResult {
  success: boolean;
  imageData?: string; // base64 encoded image
  imageUrl?: string;
  error?: string;
  cost?: number;
}

export interface ImageProcessingHistory {
  timestamp: Date;
  prompt: string;
  provider: string;
  originalPath: string;
  processedPath?: string;
  success: boolean;
  error?: string;
}

export class AiImageProcessor {
  private static readonly DEFAULT_PROVIDER = 'openai';
  private static readonly TIMEOUT_MS = 60000; // 60 seconds for image generation

  /**
   * Process an image using AI with the given prompt
   * @param imagePath - Path to the image file
   * @param options - Processing options including prompt and provider settings
   * @returns ProcessedImageResult with the new image data or error
   */
  public static async processImage(
    imagePath: string,
    options: ImageProcessingOptions
  ): Promise<ProcessedImageResult> {
    try {
      const provider = options.provider || this.DEFAULT_PROVIDER;
      const apiKey = await this.getApiKey(provider);

      if (!apiKey) {
        return {
          success: false,
          error: l10n.t(LocalizationKey.servicesAiImageProcessorNoApiKey, provider)
        };
      }

      // Validate image exists
      if (!fs.existsSync(imagePath)) {
        return {
          success: false,
          error: l10n.t(LocalizationKey.servicesAiImageProcessorFileNotFound, imagePath)
        };
      }

      // Read and encode image
      const imageBuffer = fs.readFileSync(imagePath);
      const base64Image = imageBuffer.toString('base64');
      const mimeType = this.getMimeType(imagePath);

      Logger.info(`Processing image with ${provider}: ${imagePath}`);

      // Process based on provider
      switch (provider) {
        case 'openai':
          return await this.processWithOpenAI(base64Image, mimeType, options, apiKey);
        case 'stability':
          return await this.processWithStability(base64Image, mimeType, options, apiKey);
        case 'custom':
          return await this.processWithCustom(base64Image, mimeType, options, apiKey);
        default:
          return {
            success: false,
            error: l10n.t(LocalizationKey.servicesAiImageProcessorUnsupportedProvider, provider)
          };
      }
    } catch (error) {
      const errorMsg = (error as Error).message;
      Logger.error(`AI Image Processor: ${errorMsg}`);
      return {
        success: false,
        error: errorMsg
      };
    }
  }

  /**
   * Process image using OpenAI DALL-E API
   * @param base64Image - Base64 encoded image
   * @param mimeType - MIME type of the image
   * @param options - Processing options
   * @param apiKey - OpenAI API key
   * @returns ProcessedImageResult
   */
  private static async processWithOpenAI(
    base64Image: string,
    mimeType: string,
    options: ImageProcessingOptions,
    apiKey: string
  ): Promise<ProcessedImageResult> {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => {
        Notifications.warning(
          l10n.t(LocalizationKey.servicesAiImageProcessorTimeout, 'OpenAI')
        );
        controller.abort();
      }, this.TIMEOUT_MS);

      // Convert base64 to buffer for multipart form data
      const imageBuffer = Buffer.from(base64Image, 'base64');
      
      // Create form data
      const FormData = require('form-data');
      const formData = new FormData();
      formData.append('image', imageBuffer, {
        filename: 'image.png',
        contentType: mimeType
      });
      formData.append('prompt', options.prompt);
      formData.append('n', '1');
      formData.append('size', options.size || '1024x1024');
      
      if (options.model) {
        formData.append('model', options.model);
      }
      if (options.quality) {
        formData.append('quality', options.quality);
      }
      if (options.style) {
        formData.append('style', options.style);
      }

      const response = await fetch('https://api.openai.com/v1/images/edits', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          ...formData.getHeaders()
        },
        body: formData,
        signal: controller.signal as any
      });

      clearTimeout(timeout);

      if (!response.ok) {
        const errorData = await response.json() as any;
        throw new Error(
          errorData.error?.message || `OpenAI API error: ${response.statusText}`
        );
      }

      const data = await response.json() as any;

      if (data.data && data.data.length > 0) {
        const imageUrl = data.data[0].url;
        
        // Download the processed image
        const imageResponse = await fetch(imageUrl);
        const imageBuffer = await imageResponse.buffer();
        const base64Result = imageBuffer.toString('base64');

        Logger.info('Successfully processed image with OpenAI');
        
        return {
          success: true,
          imageData: base64Result,
          imageUrl: imageUrl
        };
      }

      return {
        success: false,
        error: l10n.t(LocalizationKey.servicesAiImageProcessorNoResult)
      };
    } catch (error) {
      const errorMsg = (error as Error).message;
      Logger.error(`OpenAI Image Processing: ${errorMsg}`);
      return {
        success: false,
        error: errorMsg
      };
    }
  }

  /**
   * Process image using Stability AI API
   * @param base64Image - Base64 encoded image
   * @param mimeType - MIME type of the image
   * @param options - Processing options
   * @param apiKey - Stability AI API key
   * @returns ProcessedImageResult
   */
  private static async processWithStability(
    base64Image: string,
    mimeType: string,
    options: ImageProcessingOptions,
    apiKey: string
  ): Promise<ProcessedImageResult> {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => {
        Notifications.warning(
          l10n.t(LocalizationKey.servicesAiImageProcessorTimeout, 'Stability AI')
        );
        controller.abort();
      }, this.TIMEOUT_MS);

      // Stability AI uses image-to-image endpoint
      const FormData = require('form-data');
      const formData = new FormData();
      
      const imageBuffer = Buffer.from(base64Image, 'base64');
      formData.append('init_image', imageBuffer, {
        filename: 'image.png',
        contentType: mimeType
      });
      formData.append('text_prompts[0][text]', options.prompt);
      formData.append('text_prompts[0][weight]', '1');
      formData.append('cfg_scale', '7');
      formData.append('samples', '1');
      formData.append('steps', '30');

      const response = await fetch(
        'https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/image-to-image',
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${apiKey}`,
            'Accept': 'application/json',
            ...formData.getHeaders()
          },
          body: formData,
          signal: controller.signal as any
        }
      );

      clearTimeout(timeout);

      if (!response.ok) {
        const errorData = await response.json() as any;
        throw new Error(
          errorData.message || `Stability AI API error: ${response.statusText}`
        );
      }

      const data = await response.json() as any;

      if (data.artifacts && data.artifacts.length > 0) {
        const base64Result = data.artifacts[0].base64;
        
        Logger.info('Successfully processed image with Stability AI');
        
        return {
          success: true,
          imageData: base64Result
        };
      }

      return {
        success: false,
        error: l10n.t(LocalizationKey.servicesAiImageProcessorNoResult)
      };
    } catch (error) {
      const errorMsg = (error as Error).message;
      Logger.error(`Stability AI Image Processing: ${errorMsg}`);
      return {
        success: false,
        error: errorMsg
      };
    }
  }

  /**
   * Process image using custom API endpoint
   * @param base64Image - Base64 encoded image
   * @param mimeType - MIME type of the image
   * @param options - Processing options
   * @param apiKey - Custom API key
   * @returns ProcessedImageResult
   */
  private static async processWithCustom(
    base64Image: string,
    mimeType: string,
    options: ImageProcessingOptions,
    apiKey: string
  ): Promise<ProcessedImageResult> {
    try {
      const customEndpoint = Settings.get<string>('ai.image.customEndpoint');
      
      if (!customEndpoint) {
        return {
          success: false,
          error: l10n.t(LocalizationKey.servicesAiImageProcessorNoCustomEndpoint)
        };
      }

      const controller = new AbortController();
      const timeout = setTimeout(() => {
        Notifications.warning(
          l10n.t(LocalizationKey.servicesAiImageProcessorTimeout, 'Custom API')
        );
        controller.abort();
      }, this.TIMEOUT_MS);

      const response = await fetch(customEndpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${apiKey}`
        },
        body: JSON.stringify({
          image: base64Image,
          mimeType: mimeType,
          prompt: options.prompt,
          ...options
        }),
        signal: controller.signal as any
      });

      clearTimeout(timeout);

      if (!response.ok) {
        const errorData = await response.json() as any;
        throw new Error(
          errorData.error || `Custom API error: ${response.statusText}`
        );
      }

      const data = await response.json() as any;

      if (data.image) {
        Logger.info('Successfully processed image with custom API');
        
        return {
          success: true,
          imageData: data.image,
          imageUrl: data.url
        };
      }

      return {
        success: false,
        error: l10n.t(LocalizationKey.servicesAiImageProcessorNoResult)
      };
    } catch (error) {
      const errorMsg = (error as Error).message;
      Logger.error(`Custom Image Processing: ${errorMsg}`);
      return {
        success: false,
        error: errorMsg
      };
    }
  }

  /**
   * Get API key for the specified provider
   * @param provider - AI provider name
   * @returns API key or undefined
   */
  private static async getApiKey(provider: string): Promise<string | undefined> {
    const settingKey = `ai.image.${provider}ApiKey`;
    const apiKey = Settings.get<string>(settingKey);
    
    if (!apiKey) {
      Notifications.error(
        l10n.t(LocalizationKey.servicesAiImageProcessorMissingApiKey, provider, settingKey)
      );
    }
    
    return apiKey;
  }

  /**
   * Get MIME type from file path
   * @param filePath - Path to the file
   * @returns MIME type string
   */
  private static getMimeType(filePath: string): string {
    const ext = path.extname(filePath).toLowerCase();
    const mimeTypes: { [key: string]: string } = {
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.jpeg': 'image/jpeg',
      '.webp': 'image/webp',
      '.gif': 'image/gif'
    };
    return mimeTypes[ext] || 'image/png';
  }

  /**
   * Check if AI image processing is enabled
   * @returns boolean indicating if feature is enabled
   */
  public static isEnabled(): boolean {
    return Settings.get<boolean>('ai.image.enabled') || false;
  }

  /**
   * Get available AI providers
   * @returns Array of provider names
   */
  public static getAvailableProviders(): string[] {
    const providers: string[] = ['openai', 'stability'];
    
    const customEndpoint = Settings.get<string>('ai.image.customEndpoint');
    if (customEndpoint) {
      providers.push('custom');
    }
    
    return providers;
  }

  /**
   * Get default prompts from settings
   * @returns Array of preset prompts
   */
  public static getDefaultPrompts(): string[] {
    return Settings.get<string[]>('ai.image.defaultPrompts') || [
      'Enhance image quality and remove noise',
      'Improve lighting and colors',
      'Remove background',
      'Make image more professional',
      'Sharpen details and increase clarity'
    ];
  }

  /**
   * Estimate processing cost
   * @param provider - AI provider
   * @param size - Image size
   * @returns Estimated cost in USD
   */
  public static estimateCost(provider: string, size: string): number {
    // Approximate costs as of 2025
    const costs: { [key: string]: { [size: string]: number } } = {
      openai: {
        '1024x1024': 0.020,
        '512x512': 0.018,
        '256x256': 0.016
      },
      stability: {
        '1024x1024': 0.010,
        '512x512': 0.008
      }
    };

    return costs[provider]?.[size] || 0.020;
  }
}
