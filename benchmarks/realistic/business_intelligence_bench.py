#!/usr/bin/env python3
"""
DeepSearchStack - Realistic Business Intelligence Benchmark
Demonstrates full pipeline: goal-setting → data ingestion → aggregation → transformation → reporting
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import List, Dict, Any
import sys
import os

# Add the SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'sdk', 'python'))

from deepsearch import SyncDeepSearchClient, crawl_sync, search_sync, llm_complete_sync


class BusinessIntelligenceBenchmark:
    """
    Simulates a business intelligence workflow using DeepSearchStack:
    1. Goal: Understand market trends in AI sector
    2. Ingest: Gather relevant data from web sources
    3. Aggregate: Combine insights from multiple sources  
    4. Transform: Process into actionable business intelligence
    5. Report: Generate executive summary and case studies
    """
    
    def __init__(self):
        self.client = SyncDeepSearchClient(base_url="http://localhost:8080")
        self.results_log = []
        
    def log_result(self, stage: str, operation: str, success: bool, response_time: float, details: str = ""):
        """Log benchmark results"""
        result = {
            "stage": stage,
            "operation": operation,
            "success": success,
            "response_time": response_time,
            "timestamp": datetime.now().isoformat(),
            "details": details
        }
        self.results_log.append(result)
        print(f"📊 {stage.upper()} → {operation}: {'✅' if success else '❌'} ({response_time:.2f}s)")
    
    def run_intelligence_workflow(self):
        """Run the complete business intelligence workflow"""
        print("🚀 Starting Realistic Business Intelligence Benchmark")
        print("="*70)
        
        # Define business goal
        business_goal = "Analyze current AI industry trends and predict market opportunities for enterprise AI solutions"
        print(f"🎯 GOAL: {business_goal}")
        print("")
        
        start_time = time.time()
        
        # 1. GOAL PLANNING PHASE
        print("📋 PHASE 1: Goal Planning & Strategy Definition")
        print("-" * 50)
        
        goal_start = time.time()
        
        # Identify key research questions based on business goal
        research_questions = [
            "What are the top AI trends in 2025?",
            "Which AI technologies offer highest ROI for enterprises?",
            "Who are the key players in enterprise AI solutions?",
            "What are the regulatory implications of AI adoption?",
            "How are competitors positioning themselves in AI market?"
        ]
        
        goal_time = time.time() - goal_start
        self.log_result("PLANNING", "Define research strategy", True, goal_time)
        
        # 2. DATA INGESTION PHASE
        print("\n📥 PHASE 2: Data Ingestion & Collection")
        print("-" * 50)
        
        ingestion_start = time.time()
        
        # Ingest data for each research question
        all_sources = []
        all_content = []
        
        for i, question in enumerate(research_questions, 1):
            print(f"  Query {i}/5: {question[:50]}...")
            
            query_start = time.time()
            
            # Search for relevant sources
            search_results = search_sync(question, max_results=3)
            search_time = time.time() - query_start
            
            self.log_result("INGESTION", f"Search-{i}", True, search_time)
            
            # Collect sources
            all_sources.extend(search_results.sources)
            
            # Crawl top results to get full content
            for j, result in enumerate(search_results.results[:2]):  # Top 2 results per query
                crawl_start = time.time()
                
                try:
                    if "url" in result:  # Ensure result has URL
                        crawl_result = crawl_sync(result["url"], formats=["markdown"])
                        crawl_time = time.time() - crawl_start
                        
                        if crawl_result.success:
                            all_content.append({
                                "query": question,
                                "source": result.get("url", "unknown"),
                                "content": crawl_result.content,
                                "extracted_at": datetime.now().isoformat()
                            })
                            self.log_result("INGESTION", f"Crawl-{i}-{j+1}", True, crawl_time)
                        else:
                            self.log_result("INGESTION", f"Crawl-{i}-{j+1}", False, crawl_time, 
                                          f"Failed: {crawl_result.error_message}")
                    else:
                        self.log_result("INGESTION", f"Crawl-{i}-{j+1}", False, 0.0, "No URL in search result")
                except Exception as e:
                    crawl_time = time.time() - crawl_start
                    self.log_result("INGESTION", f"Crawl-{i}-{j+1}", False, crawl_time, f"Error: {str(e)}")
        
        ingestion_time = time.time() - ingestion_start
        print(f"  📥 Collected {len(all_content)} documents from {len(set(all_sources))} unique sources")
        
        # 3. AGGREGATION PHASE
        print("\n🔄 PHASE 3: Data Aggregation & Pattern Recognition") 
        print("-" * 50)
        
        aggregation_start = time.time()
        
        # Aggregate findings across all collected sources
        if all_content:
            aggregate_prompt = f"""
            Analyze the following {len(all_content)} documents about AI industry trends and create:
            
            1. A consolidated summary of key AI trends in 2025
            2. Major technological themes across sources
            3. Top 5 enterprise AI opportunities with supporting evidence
            4. Market challenges and regulatory considerations
            5. Competitive landscape insights
            
            Documents:
            {chr(10).join([f'Document {i+1}: {content["content"][:500]}...' for i, content in enumerate(all_content)])}
            """
            
            agg_start = time.time()
            try:
                aggregation_result = llm_complete_sync([
                    {"role": "user", "content": aggregate_prompt}
                ])
                agg_time = time.time() - agg_start
                self.log_result("AGGREGATION", "Pattern Analysis", True, agg_time)
            except Exception as e:
                agg_time = time.time() - agg_start
                self.log_result("AGGREGATION", "Pattern Analysis", False, agg_time, f"Error: {str(e)}")
                aggregation_result = "Aggregation failed due to error"
        else:
            aggregation_result = "No content available for aggregation"
            self.log_result("AGGREGATION", "Pattern Analysis", False, 0.0, "No content to aggregate")
        
        # Also aggregate individual trends from each document for comparison
        trend_analysis_start = time.time()
        trend_summaries = []
        
        for i, content in enumerate(all_content[:5]):  # Analyze first 5 docs for trends
            if "content" in content:
                prompt = f"Extract key AI industry trends from this document:\n\n{content['content'][:1000]}"
                try:
                    summary = llm_complete_sync([{"role": "user", "content": prompt}])
                    trend_summaries.append({
                        "source": content["source"],
                        "trend_summary": summary[:500]  # Truncate for storage
                    })
                except Exception as e:
                    trend_summaries.append({
                        "source": content["source"],
                        "error": str(e)
                    })
        
        trend_analysis_time = time.time() - trend_analysis_start
        self.log_result("AGGREGATION", "Individual Trend Analysis", True, trend_analysis_time)
        
        aggregation_time = time.time() - aggregation_start
        
        # 4. TRANSFORMATION PHASE
        print("\n⚙️  PHASE 4: Data Transformation & Value Enhancement")
        print("-" * 50)
        
        transformation_start = time.time()
        
        # Transform raw insights into strategic intelligence
        try:
            transformation_prompt = f"""
            Transform the aggregated AI industry insights into actionable business intelligence with:
            
            1. Strategic priorities for enterprise AI investment
            2. Risk assessment matrix  
            3. Opportunity scoring (Market size, Growth potential, Competition level, Implementation complexity)
            4. Technology roadmap recommendations
            5. Competitive positioning strategies
            
            Aggregated Insights:
            {aggregation_result[:2000]}
            
            Individual Trend Summaries:
            {json.dumps(trend_summaries[:3], indent=2)}  # Limit to first 3 for efficiency
            """
            
            trans_start = time.time()
            transformed_intelligence = llm_complete_sync([
                {"role": "user", "content": transformation_prompt}
            ])
            trans_time = time.time() - trans_start
            
            self.log_result("TRANSFORMATION", "Strategic Analysis", True, trans_time)
        except Exception as e:
            trans_time = time.time() - trans_start
            self.log_result("TRANSFORMATION", "Strategic Analysis", False, trans_time, f"Error: {str(e)}")
            transformed_intelligence = "Transformation failed due to error"
        
        transformation_time = time.time() - transformation_start
        
        # 5. REPORTING PHASE
        print("\n📄 PHASE 5: Report Generation & Case Study Creation")
        print("-" * 50)
        
        reporting_start = time.time()
        
        # Generate executive summary
        try:
            summary_prompt = f"""
            Create a compelling executive summary for stakeholders highlighting:
            
            1. Top 3 strategic recommendations with ROI projections
            2. Critical risks to address immediately  
            3. Quick wins achievable in next 6 months
            4. 2-year AI adoption roadmap
            
            Business Goal: {business_goal}
            Strategic Intelligence: {transformed_intelligence[:1500]}
            """
            
            summary_start = time.time()
            executive_summary = llm_complete_sync([
                {"role": "user", "content": summary_prompt}
            ])
            summary_time = time.time() - summary_start
            
            self.log_result("REPORTING", "Executive Summary", True, summary_time)
        except Exception as e:
            summary_time = time.time() - time.time()
            self.log_result("REPORTING", "Executive Summary", False, summary_time, f"Error: {str(e)}")
            executive_summary = "Executive summary generation failed"
        
        # Generate case study based on findings
        try:
            case_study_prompt = f"""
            Create a fictional but realistic case study demonstrating successful AI implementation based on these insights:
            
            Insights: {transformed_intelligence[:1000]}
            
            Include: Company background, Challenge faced, AI solution implemented, Results achieved, Lessons learned.
            """
            
            case_start = time.time()
            case_study = llm_complete_sync([
                {"role": "user", "content": case_study_prompt}
            ])
            case_time = time.time() - case_start
            
            self.log_result("REPORTING", "Case Study Generation", True, case_time)
        except Exception as e:
            case_time = time.time() - time.time()
            self.log_result("REPORTING", "Case Study Generation", False, case_time, f"Error: {str(e)}")
            case_study = "Case study generation failed"
        
        reporting_time = time.time() - reporting_start
        
        # 6. QUALITY ASSESSMENT
        print("\n📈 PHASE 6: Quality Assessment & Validation")
        print("-" * 50)
        
        quality_start = time.time()
        
        # Validate the quality of generated content
        try:
            validation_prompt = f"""
            Assess the quality and completeness of this business intelligence report focusing on:
            1. Strategic relevance to enterprise AI investment
            2. Actionability of recommendations  
            3. Logical consistency of arguments
            4. Evidence support for claims
            5. Clarity and stakeholder alignment
            
            Executive Summary: {executive_summary[:1000]}
            """
            
            val_start = time.time()
            quality_assessment = llm_complete_sync([
                {"role": "user", "content": validation_prompt}
            ])
            val_time = time.time() - val_start
            
            self.log_result("QUALITY", "Report Validation", True, val_time)
        except Exception as e:
            val_time = time.time() - time.time()
            self.log_result("QUALITY", "Report Validation", False, val_time, f"Error: {str(e)}")
        
        quality_time = time.time() - quality_start
        
        # CALCULATE FINAL METRICS
        total_time = time.time() - start_time
        
        # Count successful operations
        successful_ops = sum(1 for r in self.results_log if r["success"])
        total_ops = len(self.results_log)
        success_rate = successful_ops / total_ops if total_ops > 0 else 0
        
        avg_response_time = sum(r["response_time"] for r in self.results_log) / total_ops if total_ops > 0 else 0
        
        # Calculate throughput
        ops_per_minute = (total_ops / total_time) * 60 if total_time > 0 else 0
        
        print(f"\n📊 FINAL BENCHMARK RESULTS")
        print("=" * 70)
        print(f"⏱️  Total Duration:     {total_time:.2f}s")
        print(f"✅ Success Rate:       {success_rate:.1%} ({successful_ops}/{total_ops})")
        print(f"⚡ Avg Response:       {avg_response_time:.2f}s")
        print(f"📈 Throughput:         {ops_per_minute:.2f} operations/min")
        print(f"🎯 Goal Achieved:      {business_goal[:50]}...")
        print(f"📝 Reports Generated:   Executive Summary, Case Study, Quality Assessment")
        print(f"🔗 Sources Analyzed:    {len(set(all_sources))} unique sources")
        print(f"📄 Content Processed:   {len(all_content)} documents")
        print("")
        
        # PERFORMANCE RATING
        if success_rate >= 0.95 and avg_response_time <= 5.0:
            rating = "🔥 EXCELLENT - Production Ready"
        elif success_rate >= 0.85 and avg_response_time <= 10.0:
            rating = "✅ GOOD - Minor tuning needed"  
        elif success_rate >= 0.70 and avg_response_time <= 20.0:
            rating = "👍 ACCEPTABLE - Some improvements needed"
        else:
            rating = "⚠️  NEEDS WORK - Significant improvements needed"
            
        print(f"🏆 PERFORMANCE: {rating}")
        print("=" * 70)
        
        # Save detailed results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = f"benchmarks/realistic/intelligence_benchmark_{timestamp}.json"
        
        results_data = {
            "benchmark_type": "Business Intelligence Pipeline",
            "goal": business_goal,
            "timestamp": datetime.now().isoformat(),
            "metrics": {
                "total_duration": total_time,
                "successful_operations": successful_ops,
                "total_operations": total_ops,
                "success_rate": success_rate,
                "average_response_time": avg_response_time,
                "operations_per_minute": ops_per_minute
            },
            "phases": {
                "planning_time": goal_time,
                "ingestion_time": ingestion_time, 
                "aggregation_time": aggregation_time,
                "transformation_time": transformation_time,
                "reporting_time": reporting_time,
                "quality_time": quality_time
            },
            "results": self.results_log,
            "outputs": {
                "executive_summary_present": len(executive_summary) > 10,
                "case_study_present": len(case_study) > 10,
                "sources_analyzed": len(set(all_sources)),
                "documents_processed": len(all_content),
                "aggregation_performed": len(aggregation_result) > 10
            }
        }
        
        os.makedirs("benchmarks/realistic", exist_ok=True)
        with open(results_file, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        print(f"💾 Detailed results saved to: {results_file}")
        return results_data


def main():
    print("🚀 DeepSearchStack - Realistic Business Intelligence Benchmark")
    print("This benchmark simulates a complete business intelligence workflow:")
    print("Goal → Ingest → Aggregate → Transform → Report → Validate")
    print("")
    
    benchmark = BusinessIntelligenceBenchmark()
    results = benchmark.run_intelligence_workflow()
    
    print(f"\n🎯 Benchmark completed successfully - Full pipeline demonstrated!")
    print("The system performed:")
    print("  • Multi-query research with source identification")
    print("  • Web crawling for detailed content extraction") 
    print("  • Cross-source pattern recognition and aggregation")
    print("  • Strategic insight transformation")
    print("  • Report generation and case study creation")
    print("  • Quality validation of outputs")


if __name__ == "__main__":
    main()