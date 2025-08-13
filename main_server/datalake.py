import json
import asyncio
import aiofiles
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class DatalakeManager:
    def __init__(self, data_path: str):
        self.data_path = Path(data_path)
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.write_lock = asyncio.Lock()
    
    def _get_file_path(self, date: datetime = None) -> Path:
        """Get the file path for a given date (defaults to today)"""
        if date is None:
            date = datetime.utcnow()
        
        date_str = date.strftime("%Y-%m-%d")
        return self.data_path / f"results-{date_str}.ndjson"
    
    async def append_result(self, result: Dict[str, Any]):
        """Append a result to the datalake in NDJSON format"""
        async with self.write_lock:
            try:
                file_path = self._get_file_path()
                
                # Ensure the result has a timestamp
                if 'processed_at' not in result:
                    result['processed_at'] = datetime.utcnow().isoformat()
                
                # Write to NDJSON file
                async with aiofiles.open(file_path, 'a', encoding='utf-8') as f:
                    await f.write(json.dumps(result) + '\n')
                
                logger.debug(f"Appended result to {file_path}")
                
            except Exception as e:
                logger.error(f"Failed to append result to datalake: {e}")
                raise
    
    async def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get statistics for the last N days"""
        try:
            stats = {
                "total_files": 0,
                "total_records": 0,
                "success_count": 0,
                "failure_count": 0,
                "date_range": [],
                "daily_stats": {}
            }
            
            # Get all NDJSON files in the data directory
            files = list(self.data_path.glob("results-*.ndjson"))
            stats["total_files"] = len(files)
            
            for file_path in files:
                date_str = file_path.stem.replace("results-", "")
                daily_count = 0
                daily_success = 0
                daily_failure = 0
                
                try:
                    async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                        async for line in f:
                            if line.strip():
                                try:
                                    result = json.loads(line)
                                    daily_count += 1
                                    
                                    if result.get('status') == 'succeeded':
                                        daily_success += 1
                                    elif result.get('status') == 'failed':
                                        daily_failure += 1
                                        
                                except json.JSONDecodeError:
                                    continue
                    
                    stats["daily_stats"][date_str] = {
                        "total": daily_count,
                        "succeeded": daily_success,
                        "failed": daily_failure
                    }
                    
                    stats["total_records"] += daily_count
                    stats["success_count"] += daily_success
                    stats["failure_count"] += daily_failure
                    
                except Exception as e:
                    logger.error(f"Failed to read file {file_path}: {e}")
                    continue
            
            # Get date range
            dates = sorted(stats["daily_stats"].keys())
            if dates:
                stats["date_range"] = [dates[0], dates[-1]]
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get datalake stats: {e}")
            raise
    
    async def export_date_as_json(self, date: datetime) -> List[Dict[str, Any]]:
        """Export all results for a specific date as JSON"""
        try:
            file_path = self._get_file_path(date)
            results = []
            
            if not file_path.exists():
                return results
            
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                async for line in f:
                    if line.strip():
                        try:
                            result = json.loads(line)
                            results.append(result)
                        except json.JSONDecodeError:
                            continue
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to export data for {date}: {e}")
            raise
    
    async def get_recent_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get the most recent results across all files"""
        try:
            all_results = []
            
            # Get all NDJSON files sorted by date (newest first)
            files = sorted(
                self.data_path.glob("results-*.ndjson"),
                key=lambda x: x.stem,
                reverse=True
            )
            
            for file_path in files:
                if len(all_results) >= limit:
                    break
                
                try:
                    async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                        file_results = []
                        async for line in f:
                            if line.strip():
                                try:
                                    result = json.loads(line)
                                    file_results.append(result)
                                except json.JSONDecodeError:
                                    continue
                        
                        # Sort by processed_at descending and take what we need
                        file_results.sort(
                            key=lambda x: x.get('processed_at', ''),
                            reverse=True
                        )
                        
                        remaining = limit - len(all_results)
                        all_results.extend(file_results[:remaining])
                        
                except Exception as e:
                    logger.error(f"Failed to read file {file_path}: {e}")
                    continue
            
            return all_results
            
        except Exception as e:
            logger.error(f"Failed to get recent results: {e}")
            raise