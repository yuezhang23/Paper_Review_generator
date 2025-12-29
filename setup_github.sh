#!/bin/bash
# Script to help set up GitHub repository for AI_Paper_Reviewer

echo "=========================================="
echo "GitHub Repository Setup for AI_Paper_Reviewer"
echo "=========================================="
echo ""
echo "Step 1: Create a new repository on GitHub"
echo "   - Go to: https://github.com/new"
echo "   - Repository name: AI_Paper_Reviewer"
echo "   - Description: An intelligent paper review system with OpenReview MCP integration"
echo "   - Choose Public or Private"
echo "   - DO NOT initialize with README, .gitignore, or license (we already have these)"
echo "   - Click 'Create repository'"
echo ""
echo "Step 2: Once created, GitHub will show you commands to push."
echo "   Or run these commands (replace YOUR_USERNAME with your GitHub username):"
echo ""
echo "   git remote add origin https://github.com/YOUR_USERNAME/AI_Paper_Reviewer.git"
echo "   git push -u origin main"
echo ""
read -p "Press Enter when you've created the repository on GitHub..."

echo ""
echo "Step 3: Enter your GitHub username:"
read -p "GitHub username: " GITHUB_USERNAME

if [ -z "$GITHUB_USERNAME" ]; then
    echo "Error: GitHub username is required"
    exit 1
fi

echo ""
echo "Adding remote origin..."
git remote add origin https://github.com/${GITHUB_USERNAME}/AI_Paper_Reviewer.git 2>/dev/null || git remote set-url origin https://github.com/${GITHUB_USERNAME}/AI_Paper_Reviewer.git

echo ""
echo "Pushing to GitHub..."
git push -u origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Success! Your repository is now on GitHub:"
    echo "   https://github.com/${GITHUB_USERNAME}/AI_Paper_Reviewer"
else
    echo ""
    echo "❌ Push failed. Please check:"
    echo "   1. The repository exists on GitHub"
    echo "   2. You have the correct permissions"
    echo "   3. Your GitHub credentials are set up"
    echo ""
    echo "You can also push manually with:"
    echo "   git push -u origin main"
fi

