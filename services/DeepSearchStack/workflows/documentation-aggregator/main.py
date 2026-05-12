# DeepSearchStack - Documentation Aggregator and Synthesizer
# Agentic workflow to process documentation from URLs or search terms

import asyncio
import sys
import os
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import re

# Add the SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'sdk', 'python'))

from deepsearch import SyncDeepSearchClient, crawl_sync, search_sync, llm_complete_sync


@dataclass
class DocProcessingResult:
    """Result from documentation processing"""
    original_query: str
    source_url: Optional[str]
    retrieved_content: str
    processing_steps: List[str]
    quality_score: float
    security_warnings: List[str]
    synthesis: str
    summary: str
    suggestions: List[str]


class DocumentationProcessor:
    """
    Agentic documentation processor that can handle URLs or search terms.
    If a URL is detected, it crawls the content first. Otherwise, it searches.
    Then processes through multiple specialized agents for quality checks.
    """

    def __init__(self, base_url: str = "http://localhost:8080"):
        self.client = SyncDeepSearchClient(base_url=base_url)
        self.processing_history = []

    def _is_url(self, text: str) -> bool:
        """Check if the input text is a URL"""
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:www\.)?'  # optional www.
            r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'  # domain
            r'(?:/[^\s]*)?$'  # optional path
        )
        return bool(url_pattern.match(text.strip()))

    def process_documentation(self, query: str) -> DocProcessingResult:
        """
        Main workflow: Process documentation based on URL or search term
        
        Args:
            query: Either a URL to crawl or a search term for documentation
            
        Returns:
            DocProcessingResult with processed content and analysis
        """
        steps = []
        security_warnings = []
        
        # Step 1: Determine if query is URL or search term
        if self._is_url(query):
            steps.append("URL detected - initiating crawl")
            source_url = query.strip()
            crawl_result = crawl_sync(source_url, formats=["markdown"])
            
            if crawl_result.success:
                content = crawl_result.content
                steps.append("Content crawled successfully")
            else:
                raise Exception(f"Failed to crawl URL: {crawl_result.error_message}")
        else:
            steps.append("Search term detected - initiating search")
            source_url = None
            
            # Search for the documentation topic
            search_results = search_sync(query, max_results=3)
            
            if not search_results.results:
                content = f"No relevant results found for: {query}"
            else:
                # Get content from the top result
                top_result = search_results.results[0]
                crawl_result = crawl_sync(top_result['url'], formats=["markdown"])
                
                if crawl_result.success:
                    content = crawl_result.content
                    steps.append(f"Content crawled from: {top_result['url']}")
                else:
                    content = f"Search found results but could not crawl: {top_result['url']}"
                    steps.append(f"Failed to crawl: {top_result['url']}")
        
        # Step 2: Test Agent - Verify content validity and structure
        test_agent_result = self._test_content_agent(content, query)
        steps.append("Test agent validation completed")
        
        # Step 3: Quality Check Agent - Assess quality and completeness
        quality_result = self._quality_check_agent(content, query)
        steps.append("Quality agent assessment completed")
        
        # Step 4: Security Audit Agent - Scan for security concerns
        security_warnings = self._security_audit_agent(content)
        steps.append("Security audit completed")
        
        # Step 5: Synthesis Agent - Create comprehensive synthesis
        synthesis = self._synthesis_agent(content, query, test_agent_result, quality_result)
        steps.append("Content synthesis completed")
        
        # Step 6: Summary Agent - Create concise summary
        summary = self._summary_agent(synthesis)
        steps.append("Summary generation completed")
        
        # Step 7: Suggestions Agent - Generate improvement suggestions
        suggestions = self._suggestions_agent(content, synthesis)
        steps.append("Suggestions generation completed")
        
        return DocProcessingResult(
            original_query=query,
            source_url=source_url,
            retrieved_content=content,
            processing_steps=steps,
            quality_score=quality_result.get('score', 0.0),
            security_warnings=security_warnings,
            synthesis=synthesis,
            summary=summary,
            suggestions=suggestions
        )
    
    def _test_content_agent(self, content: str, query: str) -> Dict[str, Any]:
        """Test agent: Validates content structure and relevance"""
        # Determine if the content is relevant to the query
        query_keywords = query.lower().split()
        content_lower = content.lower()
        
        # Check if content contains query keywords
        matches = sum(1 for keyword in query_keywords if keyword in content_lower)
        relevance_score = min(matches / len(query_keywords), 1.0) if query_keywords else 0.0
        
        # Check content length and structure
        content_length = len(content)
        has_structure = '\n#' in content or '\n##' in content or '\n###' in content  # Markdown headers
        
        return {
            "valid": content_length > 10 and (relevance_score > 0.1 or has_structure),
            "relevance_score": relevance_score,
            "length": content_length,
            "has_structure": has_structure,
            "issues": [] if content_length > 10 else ["Content too short (<10 chars)"]
        }
    
    def _quality_check_agent(self, content: str, query: str) -> Dict[str, Any]:
        """Quality check agent: Assesses content quality and completeness"""
        score = 0.0
        
        # Metrics for quality assessment
        content_length = len(content)
        
        # Length-based score (0-0.3)
        if content_length > 2000:
            length_score = 0.3
        elif content_length > 1000:
            length_score = 0.2
        elif content_length > 500:
            length_score = 0.15
        elif content_length > 100:
            length_score = 0.05
        else:
            length_score = 0.0
        
        # Structure-based score (0-0.3)
        structure_score = 0.0
        if '# ' in content:  # Headers in markdown
            structure_score += 0.1
        if '## ' in content:
            structure_score += 0.05
        if '### ' in content:
            structure_score += 0.05
        if '```' in content:  # Code blocks
            structure_score += 0.1
        if '`' in content:  # Inline code
            structure_score += 0.05
            
        # Relevance-based score (0-0.4)
        query_words = query.lower().split()
        content_lower = content.lower()
        relevant_word_count = sum(1 for word in query_words if word in content_lower and len(word) > 3)
        relevance_score = min(0.4, relevant_word_count * 0.1)
        
        score = min(1.0, length_score + structure_score + relevance_score)
        
        return {
            "score": score,
            "breakdown": {
                "length": length_score,
                "structure": structure_score,
                "relevance": relevance_score,
            },
            "feedback": f"Content quality rated at {score*100:.1f}% based on length, structure, and relevance."
        }
    
    def _security_audit_agent(self, content: str) -> List[str]:
        """Security audit agent: Identifies potential security concerns"""
        warnings = []
        
        # Check for insecure patterns (hardcoded passwords, API keys, etc.)
        patterns = [
            (r'\b(?:password|pwd|pass)\s*[=:]\s*["\'][^"\']{5,15}["\']', "Potential hardcoded password found"),
            (r'\b(?:token|key|secret|api_key)\s*[=:]\s*["\'][^"\']{10,}["\']', "Potential hard-coded secret/token found"),
            (r'ftp://[^\s]+', "Insecure FTP URL found"),
            (r'http://[^/\s]*\.onion', "Tor URL found"),
            (r'<script[^>]*>.*?</script>', "Possible XSS vulnerability in embedded script"),
        ]
        
        for pattern, warning in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                warnings.append(warning)
        
        return warnings
    
    def _synthesis_agent(self, content: str, query: str, test_result: Dict, quality_result: Dict) -> str:
        """Synthesis agent: Creates comprehensive synthesis from content"""
        prompt = f"""
        Create a well-structured synthesis of the following documentation content based on the query "{query}":

        Documentation Content:
        {content[:3000]}  # Limit to first 3000 characters for efficiency

        Context:
        - Content validation: {test_result['valid']}
        - Quality score: {quality_result['score']:.2f}
        - Content length: {len(content)} characters

        Provide a comprehensive synthesis that:
        1. Addresses the original query '{query}'
        2. Organizes the information in a logical structure
        3. Highlights the most important aspects
        4. Points out any gaps identified in the content
        5. Maintains technical accuracy
        """
        
        try:
            response = llm_complete_sync([
                {"role": "user", "content": prompt}
            ])
            return response
        except Exception:
            return f"Could not synthesize documentation for query: {query}"
    
    def _summary_agent(self, synthesis: str) -> str:
        """Summary agent: Creates a concise summary of the synthesis"""
        if len(synthesis) < 50:
            return synthesis
            
        prompt = f"""
        Create a concise summary (under 150 words) of the following content:

        Content:
        {synthesis[:2000]}  # Limit to first 2000 characters for efficiency

        The summary should capture the key points accurately without losing important information.
        """
        
        try:
            response = llm_complete_sync([
                {"role": "user", "content": prompt}
            ])
            return response
        except Exception:
            return f"Could not create summary: Content too long or processing error"
    
    def _suggestions_agent(self, content: str, synthesis: str) -> List[str]:
        """Suggestions agent: Generates improvement suggestions"""
        issues = []
        
        if len(content) < 500:
            issues.append("Consider expanding with more detailed documentation")
        
        if '# ' not in content and '## ' not in content:
            issues.append("Structure content with headings and sections")
        
        if '```' not in content:
            issues.append("Add code examples to illustrate concepts")
        
        if len(issues) == 0:
            issues = ["Consider adding more visual elements like diagrams or flowcharts"]
        
        # Ask LLM for additional suggestions
        prompt = f"""
        Based on this documentation content and synthesis, suggest 3-5 improvements:

        Original Content:
        {content[:1000]}

        Synthesis:
        {synthesis[:1000]}

        Current suggestions based on content analysis:
        {', '.join(issues)}

        Please provide 3-5 specific, actionable suggestions for improving the documentation.
        """
        
        try:
            response = llm_complete_sync([
                {"role": "user", "content": prompt}
            ])
            suggestions = [s.strip() for s in response.split('\n') if s.strip()]
            return suggestions or issues
        except Exception:
            return issues


def main():
    """Example usage of the Documentation Processor"""
    print("📚 DeepSearchStack - Documentation Aggregator and Synthesizer")
    print("="*70)

    processor = DocumentationProcessor()

    # Example 1: Process a URL
    print("Example 1: Processing documentation from URL")
    print("-"*50)
    try:
        result1 = processor.process_documentation("https://example.com")
        print(f"✅ Query: {result1.original_query}")
        print(f"📖 Source: {result1.source_url}")
        print(f"🔍 Summary: {result1.summary[:200]}...")
        print(f"✅ Quality Score: {result1.quality_score:.2f}")
        print(f"⚠️  Security Warnings: {len(result1.security_warnings)}")
        print(f"💡 Suggestions: {len(result1.suggestions)}")
    except Exception as e:
        print(f"❌ Error processing URL: {e}")
    print()

    # Example 2: Process a search term
    print("Example 2: Processing documentation from search term")
    print("-"*50)
    try:
        result2 = processor.process_documentation("Python API basics")
        print(f"✅ Query: {result2.original_query}")
        print(f"📖 Source: {result2.source_url}")
        print(f"🔍 Summary: {result2.summary[:200]}...")
        print(f"✅ Quality Score: {result2.quality_score:.2f}")
        print(f"⚠️  Security Warnings: {len(result2.security_warnings)}")
        print(f"💡 Suggestions: {len(result2.suggestions)}")
    except Exception as e:
        print(f"❌ Error processing search term: {e}")
    print()

    print("🎯 Documentation processing workflow completed!")
    print("Each agent performed its specialized task:")
    print("  • Test Agent: Validated content structure and relevance")
    print("  • Quality Check Agent: Assessed content completeness")
    print("  • Security Audit Agent: Scanned for potential vulnerabilities")
    print("  • Synthesis Agent: Integrated and organized information")
    print("  • Summary Agent: Created concise overview")
    print("  • Suggestions Agent: Provided improvement recommendations")


if __name__ == "__main__":
    main()