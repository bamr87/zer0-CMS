import * as fs from 'fs';
import * as path from 'path';
import { workspace } from 'vscode';
import { Logger } from './Logger';
import { ImageProcessingHistory } from '../services/AiImageProcessor';
import { MediaInfo } from '../models/MediaPaths';

export class ImageBackup {
  private static readonly BACKUP_FOLDER_NAME = '.frontmatter-backups';
  private static readonly HISTORY_FILE_NAME = 'processing-history.json';

  /**
   * Create a backup of an image before processing
   * @param imagePath - Path to the image file
   * @returns Path to the backup file
   */
  public static async createBackup(imagePath: string): Promise<string | undefined> {
    try {
      if (!fs.existsSync(imagePath)) {
        Logger.error(`Image file not found: ${imagePath}`);
        return undefined;
      }

      const workspaceFolder = workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        Logger.error('No workspace folder found');
        return undefined;
      }

      // Create backup folder if it doesn't exist
      const backupFolder = path.join(workspaceFolder.uri.fsPath, this.BACKUP_FOLDER_NAME);
      if (!fs.existsSync(backupFolder)) {
        fs.mkdirSync(backupFolder, { recursive: true });
      }

      // Generate backup filename with timestamp
      const fileName = path.basename(imagePath);
      const timestamp = new Date().getTime();
      const backupFileName = `${timestamp}-${fileName}`;
      const backupPath = path.join(backupFolder, backupFileName);

      // Copy file to backup location
      fs.copyFileSync(imagePath, backupPath);

      Logger.info(`Created backup: ${backupPath}`);
      return backupPath;
    } catch (error) {
      Logger.error(`Failed to create backup: ${(error as Error).message}`);
      return undefined;
    }
  }

  /**
   * Restore an image from backup
   * @param backupPath - Path to the backup file
   * @param targetPath - Path to restore the image to
   * @returns Success boolean
   */
  public static async restoreBackup(backupPath: string, targetPath: string): Promise<boolean> {
    try {
      if (!fs.existsSync(backupPath)) {
        Logger.error(`Backup file not found: ${backupPath}`);
        return false;
      }

      // Copy backup to target location
      fs.copyFileSync(backupPath, targetPath);

      Logger.info(`Restored backup from ${backupPath} to ${targetPath}`);
      return true;
    } catch (error) {
      Logger.error(`Failed to restore backup: ${(error as Error).message}`);
      return false;
    }
  }

  /**
   * Get all backups for a specific image
   * @param imagePath - Path to the original image
   * @returns Array of backup file paths
   */
  public static async getBackups(imagePath: string): Promise<string[]> {
    try {
      const workspaceFolder = workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }

      const backupFolder = path.join(workspaceFolder.uri.fsPath, this.BACKUP_FOLDER_NAME);
      if (!fs.existsSync(backupFolder)) {
        return [];
      }

      const fileName = path.basename(imagePath);
      const backups = fs
        .readdirSync(backupFolder)
        .filter((file) => file.endsWith(fileName))
        .map((file) => path.join(backupFolder, file))
        .sort((a, b) => {
          // Sort by timestamp (newest first)
          const aTime = fs.statSync(a).mtime.getTime();
          const bTime = fs.statSync(b).mtime.getTime();
          return bTime - aTime;
        });

      return backups;
    } catch (error) {
      Logger.error(`Failed to get backups: ${(error as Error).message}`);
      return [];
    }
  }

  /**
   * Delete a backup file
   * @param backupPath - Path to the backup file
   * @returns Success boolean
   */
  public static async deleteBackup(backupPath: string): Promise<boolean> {
    try {
      if (!fs.existsSync(backupPath)) {
        Logger.error(`Backup file not found: ${backupPath}`);
        return false;
      }

      fs.unlinkSync(backupPath);

      Logger.info(`Deleted backup: ${backupPath}`);
      return true;
    } catch (error) {
      Logger.error(`Failed to delete backup: ${(error as Error).message}`);
      return false;
    }
  }

  /**
   * Add processing history entry
   * @param imagePath - Path to the image
   * @param history - History entry to add
   */
  public static async addHistory(
    imagePath: string,
    history: ImageProcessingHistory
  ): Promise<void> {
    try {
      const workspaceFolder = workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return;
      }

      const backupFolder = path.join(workspaceFolder.uri.fsPath, this.BACKUP_FOLDER_NAME);
      if (!fs.existsSync(backupFolder)) {
        fs.mkdirSync(backupFolder, { recursive: true });
      }

      const historyFile = path.join(backupFolder, this.HISTORY_FILE_NAME);
      let historyData: { [imagePath: string]: ImageProcessingHistory[] } = {};

      // Read existing history
      if (fs.existsSync(historyFile)) {
        const content = fs.readFileSync(historyFile, 'utf-8');
        historyData = JSON.parse(content);
      }

      // Add new history entry
      if (!historyData[imagePath]) {
        historyData[imagePath] = [];
      }
      historyData[imagePath].unshift(history);

      // Keep only last 10 entries per image
      if (historyData[imagePath].length > 10) {
        historyData[imagePath] = historyData[imagePath].slice(0, 10);
      }

      // Write updated history
      fs.writeFileSync(historyFile, JSON.stringify(historyData, null, 2), 'utf-8');

      Logger.info(`Added processing history for: ${imagePath}`);
    } catch (error) {
      Logger.error(`Failed to add history: ${(error as Error).message}`);
    }
  }

  /**
   * Get processing history for an image
   * @param imagePath - Path to the image
   * @returns Array of history entries
   */
  public static async getHistory(imagePath: string): Promise<ImageProcessingHistory[]> {
    try {
      const workspaceFolder = workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return [];
      }

      const backupFolder = path.join(workspaceFolder.uri.fsPath, this.BACKUP_FOLDER_NAME);
      const historyFile = path.join(backupFolder, this.HISTORY_FILE_NAME);

      if (!fs.existsSync(historyFile)) {
        return [];
      }

      const content = fs.readFileSync(historyFile, 'utf-8');
      const historyData: { [imagePath: string]: ImageProcessingHistory[] } = JSON.parse(content);

      return historyData[imagePath] || [];
    } catch (error) {
      Logger.error(`Failed to get history: ${(error as Error).message}`);
      return [];
    }
  }

  /**
   * Clear all backups and history
   * @returns Success boolean
   */
  public static async clearAll(): Promise<boolean> {
    try {
      const workspaceFolder = workspace.workspaceFolders?.[0];
      if (!workspaceFolder) {
        return false;
      }

      const backupFolder = path.join(workspaceFolder.uri.fsPath, this.BACKUP_FOLDER_NAME);
      if (fs.existsSync(backupFolder)) {
        fs.rmSync(backupFolder, { recursive: true, force: true });
        Logger.info('Cleared all backups and history');
        return true;
      }

      return false;
    } catch (error) {
      Logger.error(`Failed to clear backups: ${(error as Error).message}`);
      return false;
    }
  }

  /**
   * Extend MediaInfo with processing history
   * @param mediaInfo - Media info object
   * @returns Extended media info with history
   */
  public static async extendMediaInfo(mediaInfo: MediaInfo): Promise<MediaInfo> {
    try {
      const history = await this.getHistory(mediaInfo.fsPath);
      
      return {
        ...mediaInfo,
        metadata: {
          ...mediaInfo.metadata,
          processingHistory: history
        }
      };
    } catch (error) {
      Logger.error(`Failed to extend media info: ${(error as Error).message}`);
      return mediaInfo;
    }
  }
}
