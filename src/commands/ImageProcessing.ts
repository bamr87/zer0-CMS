import { commands, window } from 'vscode';
import { COMMAND_NAME } from '../constants';
import { Extension } from '../helpers/Extension';
import { AiImageProcessor } from '../services/AiImageProcessor';
import { Logger, Notifications } from '../helpers';
import * as l10n from '@vscode/l10n';
import { LocalizationKey } from '../localization';
import { Dashboard } from './Dashboard';
import { DashboardData } from '../models/DashboardData';
import { NavigationType } from '../dashboardWebView/models';

export class ImageProcessing {
  /**
   * Register the image processing commands
   */
  public static registerCommands() {
    const subscriptions = Extension.getInstance().subscriptions;

    subscriptions.push(
      commands.registerCommand(COMMAND_NAME.processPreviewImage, ImageProcessing.process)
    );
  }

  /**
   * Process a preview image with AI
   * @param imagePath - Path to the image file
   * @param prompt - Processing prompt
   * @param options - Additional processing options
   */
  public static async process(
    imagePath?: string,
    prompt?: string,
    options?: any
  ): Promise<void> {
    try {
      // Check if feature is enabled
      if (!AiImageProcessor.isEnabled()) {
        Notifications.warning(
          l10n.t(LocalizationKey.commandsImageProcessingDisabled)
        );
        return;
      }

      // If no image path provided, open media dashboard
      if (!imagePath) {
        await Dashboard.open({ type: NavigationType.Media });
        return;
      }

      // If no prompt provided, show input box
      if (!prompt) {
        const defaultPrompts = AiImageProcessor.getDefaultPrompts();
        const selectedPrompt = await window.showQuickPick(
          [...defaultPrompts, l10n.t(LocalizationKey.commandsImageProcessingCustomPrompt)],
          {
            placeHolder: l10n.t(LocalizationKey.commandsImageProcessingSelectPrompt),
            ignoreFocusOut: true
          }
        );

        if (!selectedPrompt) {
          return;
        }

        if (selectedPrompt === l10n.t(LocalizationKey.commandsImageProcessingCustomPrompt)) {
          prompt = await window.showInputBox({
            prompt: l10n.t(LocalizationKey.commandsImageProcessingEnterPrompt),
            placeHolder: l10n.t(LocalizationKey.commandsImageProcessingPromptPlaceholder),
            ignoreFocusOut: true
          });

          if (!prompt) {
            return;
          }
        } else {
          prompt = selectedPrompt;
        }
      }

      // Show provider selection
      const providers = AiImageProcessor.getAvailableProviders();
      const selectedProvider = await window.showQuickPick(providers, {
        placeHolder: l10n.t(LocalizationKey.commandsImageProcessingSelectProvider),
        ignoreFocusOut: true
      });

      if (!selectedProvider) {
        return;
      }

      // Estimate cost
      const estimatedCost = AiImageProcessor.estimateCost(selectedProvider, '1024x1024');
      const proceed = await window.showInformationMessage(
        l10n.t(
          LocalizationKey.commandsImageProcessingConfirm,
          selectedProvider,
          estimatedCost.toFixed(3)
        ),
        l10n.t(LocalizationKey.commonProceed),
        l10n.t(LocalizationKey.commonCancel)
      );

      if (proceed !== l10n.t(LocalizationKey.commonProceed)) {
        return;
      }

      // Show progress
      await window.withProgress(
        {
          location: 15,
          title: l10n.t(LocalizationKey.commandsImageProcessingProgress),
          cancellable: false
        },
        async (progress) => {
          progress.report({ increment: 0 });

          // Process the image
          const result = await AiImageProcessor.processImage(imagePath, {
            prompt,
            provider: selectedProvider as 'openai' | 'stability' | 'custom',
            ...options
          });

          progress.report({ increment: 100 });

          if (result.success && result.imageData) {
            Notifications.info(
              l10n.t(LocalizationKey.commandsImageProcessingSuccess)
            );
            
            Logger.info(`Successfully processed image: ${imagePath}`);
            
            // Return the processed image data for the caller to handle
            return result;
          } else {
            Notifications.error(
              l10n.t(LocalizationKey.commandsImageProcessingFailed, result.error || 'Unknown error')
            );
            Logger.error(`Failed to process image: ${result.error}`);
          }
        }
      );
    } catch (error) {
      const errorMsg = (error as Error).message;
      Logger.error(`Image Processing Command: ${errorMsg}`);
      Notifications.error(
        l10n.t(LocalizationKey.commandsImageProcessingError, errorMsg)
      );
    }
  }

  /**
   * Get available AI providers
   * @returns Array of provider names
   */
  public static getProviders(): string[] {
    return AiImageProcessor.getAvailableProviders();
  }

  /**
   * Get default processing prompts
   * @returns Array of preset prompts
   */
  public static getPrompts(): string[] {
    return AiImageProcessor.getDefaultPrompts();
  }

  /**
   * Estimate processing cost
   * @param provider - AI provider
   * @param size - Image size
   * @returns Estimated cost in USD
   */
  public static estimateCost(provider: string, size: string): number {
    return AiImageProcessor.estimateCost(provider, size);
  }
}
